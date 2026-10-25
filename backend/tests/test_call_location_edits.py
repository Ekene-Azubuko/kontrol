"""Dispatcher location correction, retry, provenance and stale-result boundaries."""

import json

import pytest
from sqlalchemy import select

from app import call_services, call_worker, worker
from app.call_location import EDITED_LOCATION_LIMITATION
from app.config import settings
from app.models import AgentRun, Call, CoordinatorAction
from call_helpers import COORDINATOR


def ready_call(client):
    """Create a transcribed sample through the same API and worker used by the dispatcher screen."""
    call = client.post("/calls/sample/collision", headers=COORDINATOR).json()
    assert call_worker.process_one_call()
    return client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()


def test_edit_retry_and_start_preserve_transcript_and_audit(system):
    """Edited text controls the response location while original call evidence and uncertainty survive."""
    client, factory = system
    call = ready_call(client)
    path = f"/calls/{call['id']}/locate"
    updated = client.post(
        path,
        headers=COORDINATOR,
        json={
            "version": call["version"],
            "address": "  Richmond exercise block  ",
        },
    )
    assert updated.status_code == 200, updated.text
    edited = updated.json()
    assert edited["original_transcript"] == call["original_transcript"]
    assert edited["detected_location"]["address"] == "Richmond exercise block"
    assert edited["detected_location"]["input_address"] == "Richmond exercise block"
    assert edited["detected_location"]["input_source"] == "dispatcher_address"
    assert edited["detected_location"]["latitude"] == 37.780
    assert edited["version"] > call["version"] and edited["attempts"] == 1
    assert client.post(path, headers=COORDINATOR, json={"version": call["version"]}).status_code == 409
    retried = client.post(path, headers=COORDINATOR, json={"version": edited["version"]}).json()
    assert retried["detected_location"] == edited["detected_location"]
    assert retried["version"] > edited["version"]
    with factory() as db:
        assert not db.scalar(select(AgentRun))
        audits = list(
            db.scalars(select(CoordinatorAction).where(CoordinatorAction.action == "call_location_lookup"))
        )
        assert len(audits) == 2
        change = json.loads(audits[0].details)
        assert change["previous_location"]["address"] == "Market & 8th exercise area"
        assert change["location"]["input_address"] == "Richmond exercise block"
        assert change["transcript_changed"] is False
    started = client.post(
        f"/calls/{call['id']}/start",
        headers=COORDINATOR,
        json={
            "version": retried["version"],
            "category": "collision",
        },
    ).json()
    assert started["confirmed_latitude"] == 37.780
    assert started["reviewed_transcript"] == call["original_transcript"]
    for _ in range(4):
        assert worker.process_one()
    plan = client.get(f"/response-plans/{started['plan_id']}", headers=COORDINATOR).json()
    assert EDITED_LOCATION_LIMITATION in plan["constraints"]
    intake = next(run for run in plan["runs"] if run["stage"] == "intake")
    assert intake["input"]["agent_input"]["confirmed_location"]["address"] == "Richmond exercise block"
    assert client.post(path, headers=COORDINATOR, json={"version": started["version"]}).status_code == 409


def test_failed_correction_removes_obsolete_pin_and_can_recover(system):
    """A failed lookup cannot leave the original location eligible for dispatch."""
    client, _ = system
    call = ready_call(client)
    path = f"/calls/{call['id']}/locate"
    missing = client.post(
        path,
        headers=COORDINATOR,
        json={
            "version": call["version"],
            "address": "Unknown location",
        },
    ).json()
    assert missing["detected_location"]["status"] == "unavailable"
    assert missing["detected_location"]["latitude"] is None
    assert missing["detected_location"]["input_address"] == "Unknown location"
    assert (
        client.post(
            f"/calls/{call['id']}/start",
            headers=COORDINATOR,
            json={
                "version": missing["version"],
                "category": "collision",
            },
        ).status_code
        == 409
    )
    recovered = client.post(
        path,
        headers=COORDINATOR,
        json={
            "version": missing["version"],
            "address": "Mission exercise block",
        },
    ).json()
    assert recovered["detected_location"]["status"] == "resolved"
    assert recovered["original_transcript"] == call["original_transcript"]


def test_retry_without_correction_uses_transcript_and_no_paid_work(system, monkeypatch):
    """Location retries remain available with paid simulation disabled and do not retranscribe audio."""
    client, _ = system
    call = ready_call(client)
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "live_simulation_enabled", False)
    response = client.post(
        f"/calls/{call['id']}/locate", headers=COORDINATOR, json={"version": call["version"]}
    )
    assert response.status_code == 200
    assert response.json()["detected_location"]["input_source"] == "transcript"
    assert response.json()["detected_location"]["input_address"] is None
    assert response.json()["attempts"] == 1


@pytest.mark.parametrize(
    "extra",
    [
        {"address": "   "},
        {"address": "x" * 161},
        {"address": 123},
        {"latitude": 37.7},
        {"version": 0},
    ],
)
def test_invalid_location_edit_is_rejected(system, extra):
    """Reject malformed corrections and client-supplied coordinates before lookup."""
    client, _ = system
    call = ready_call(client)
    response = client.post(
        f"/calls/{call['id']}/locate", headers=COORDINATOR, json={"version": call["version"], **extra}
    )
    assert response.status_code == 422
    assert client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()["version"] == call["version"]


def test_late_lookup_cannot_replace_newer_state(system, monkeypatch):
    """Reject a stale geocoding response after another transaction changes the call during lookup."""
    client, factory = system
    call = ready_call(client)
    original = call_services.detect_location

    def changed_while_resolving(text):
        """Simulate a reset while the external request runs outside the database transaction."""
        with factory() as db:
            row = db.get(Call, call["id"])
            row.status = "failed"
            db.commit()
        return original(text)

    monkeypatch.setattr(call_services, "detect_location", changed_while_resolving)
    response = client.post(
        f"/calls/{call['id']}/locate",
        headers=COORDINATOR,
        json={
            "version": call["version"],
            "address": "Richmond exercise block",
        },
    )
    assert response.status_code == 409
    with factory() as db:
        row = db.get(Call, call["id"])
        assert row.status == "failed" and row.detected_location == call["detected_location"]
        assert not db.scalar(
            select(CoordinatorAction).where(CoordinatorAction.action == "call_location_lookup")
        )
