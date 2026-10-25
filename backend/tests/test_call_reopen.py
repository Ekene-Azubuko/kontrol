"""Verify explicit reruns preserve recordings and cannot undo approved resource assignments."""

import json

import pytest
from sqlalchemy import func, select

from app import worker
from app.config import settings
from app.creao import MockAdapter
from app.db import now
from app.models import AgentRun, Call, CoordinatorAction, Incident, Report, ResponsePlan
from call_helpers import COORDINATOR, submit_call


def test_reopen_preserves_recording_and_starts_fresh_jobs(system, monkeypatch):
    """Return a failed call to review, then start another category with new remote execution identities."""
    client, factory = system
    call = submit_call(client).json()
    audio = client.get(f"/calls/{call['id']}/audio", headers=COORDINATOR).content
    with factory() as db:
        plan = db.get(ResponsePlan, call["plan_id"])
        plan.status = "failed"
        run = db.scalar(select(AgentRun))
        run.status, run.remote_id, run.error = "failed", "old-remote-id", "Invalid provider result"
        run.raw_response = {"status": "completed", "result": {"text": "Old response"}}
        old_job_id = run.id
        db.commit()
    # Returning to review creates no paid work and remains possible when live execution is disabled.
    monkeypatch.setattr(settings, "creao_mode", "live")
    result = client.post(f"/calls/{call['id']}/reopen", headers=COORDINATOR, json={"version": call["version"]})
    assert result.status_code == 200, result.text
    reopened = result.json()
    assert reopened["status"] == "awaiting_review" and reopened["report_id"] is None
    assert reopened["plan_id"] is None and not reopened["can_reopen"]
    for key in ["original_transcript", "received_at", "detected_location", "caller_latitude", "attempts"]:
        assert reopened[key] == call[key]
    assert client.get(f"/calls/{call['id']}/audio", headers=COORDINATOR).content == audio
    assert client.post(f"/calls/{call['id']}/reopen", headers=COORDINATOR,
                       json={"version": call["version"]}).status_code == 409
    body = {"version": reopened["version"], "category": "medical"}
    assert client.post(f"/calls/{call['id']}/start", headers=COORDINATOR, json=body).status_code == 409
    with factory() as db:
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 1
        assert db.get(ResponsePlan, call["plan_id"]).status == "cancelled"
        audit = db.scalar(select(CoordinatorAction).where(CoordinatorAction.action == "call_reopen"))
        assert json.loads(audit.details)["previous_report_id"] == call["report_id"]
    monkeypatch.setattr(settings, "creao_mode", "mock")
    restarted = client.post(f"/calls/{call['id']}/start", headers=COORDINATOR, json=body)
    assert restarted.status_code == 200, restarted.text
    fresh = restarted.json()
    assert fresh["id"] == call["id"] and fresh["plan_id"] != call["plan_id"]
    assert fresh["report_id"] != call["report_id"]
    assert client.post(f"/calls/{call['id']}/start", headers=COORDINATOR, json=body).status_code == 409
    with factory() as db:
        old = db.get(AgentRun, old_job_id)
        assert old.status == "failed" and old.remote_id == "old-remote-id" and old.raw_response
        new = db.scalar(select(AgentRun).where(AgentRun.plan_id == fresh["plan_id"]))
        assert new.id != old.id and new.remote_id is None and new.attempts == 0
        assert db.get(Report, fresh["report_id"]).category == "medical"
        assert db.get(Report, call["report_id"]).category == "collision"
        assert db.scalar(select(func.count()).select_from(Call)) == 1
    for _ in range(4):
        assert worker.process_one()
    assert client.get(f"/response-plans/{fresh['plan_id']}", headers=COORDINATOR).json()["status"] in {
        "awaiting_approval", "needs_information",
    }


def test_reopen_discards_late_agent_result(system, monkeypatch):
    """An old provider result arriving after reopening cannot enqueue stages in the new workflow."""
    client, factory = system
    call = submit_call(client).json()

    class HeldAdapter:
        """Reopen while a remote-shaped stage executes outside its database transaction."""

        def invoke(self, stage, payload):
            """Complete the old result after the dispatcher has returned and started again."""
            reopened = client.post(f"/calls/{call['id']}/reopen", headers=COORDINATOR,
                                   json={"version": call["version"]})
            assert reopened.status_code == 200
            result = client.post(f"/calls/{call['id']}/start", headers=COORDINATOR,
                                 json={"version": reopened.json()["version"], "category": "medical"})
            assert result.status_code == 200
            return MockAdapter().invoke(stage, payload)

    monkeypatch.setattr(worker, "get_adapter", HeldAdapter)
    assert worker.process_one()
    with factory() as db:
        old_runs = list(db.scalars(select(AgentRun).where(AgentRun.plan_id == call["plan_id"])))
        assert len(old_runs) == 1 and old_runs[0].status == "cancelled" and old_runs[0].output is None
        assert db.get(ResponsePlan, call["plan_id"]).status == "cancelled"
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 2


@pytest.mark.parametrize("status", ["approved", "dispatching", "completed"])
def test_approved_responses_cannot_reopen(system, status):
    """Never use recording reruns as a way to release or repeat an approved response."""
    client, factory = system
    call = submit_call(client).json()
    with factory() as db:
        plan = db.get(ResponsePlan, call["plan_id"])
        plan.status, plan.approved_at = status, now()
        db.commit()
    assert not client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()["can_reopen"]
    response = client.post(f"/calls/{call['id']}/reopen", headers=COORDINATOR,
                           json={"version": call["version"]})
    assert response.status_code == 409 and "approved" in response.text
    assert client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()["status"] == "confirmed"


def test_reopen_requires_current_version_and_rolls_back_atomically(system, monkeypatch):
    """Reject stale versions, and roll back both workflow cancellation and the call when saving fails."""
    from app import call_api

    client, factory = system
    call = submit_call(client).json()
    path = f"/calls/{call['id']}/reopen"
    assert client.post(path, headers=COORDINATOR, json={"version": call["version"] - 1}).status_code == 409
    original = call_api.reopen_call

    def broken(*args):
        """Fail after flushing the changes so the request transaction must undo them all."""
        original(*args)
        raise RuntimeError("test rollback")

    monkeypatch.setattr(call_api, "reopen_call", broken)
    with pytest.raises(RuntimeError, match="test rollback"):
        client.post(path, headers=COORDINATOR, json={"version": call["version"]})
    with factory() as db:
        assert db.get(Call, call["id"]).status == "confirmed"
        assert db.get(ResponsePlan, call["plan_id"]).status == "generating"
        assert db.get(Incident, call["incident_id"]).response_status == "generating"
        assert db.scalar(select(AgentRun)).status == "queued"
        assert not db.scalar(select(CoordinatorAction).where(CoordinatorAction.action == "call_reopen"))
