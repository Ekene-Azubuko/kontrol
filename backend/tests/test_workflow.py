"""Exercise permission boundaries, durable ingestion and the full mock workflow."""

import os

os.environ["DATABASE_URL"] = "sqlite://"
os.environ["CREAO_MODE"] = "mock"

from datetime import datetime, timezone
import pytest
from pydantic import ValidationError
from sqlalchemy import select
from app import worker
from call_helpers import submit_call
from app.models import AgentRun, Resource
from app.response_schemas import IntakeResult as Assessment
from app.creao import MockAdapter
from app.config import settings

RESIDENT = {"Authorization": "Bearer demo-resident"}
COORDINATOR = {"Authorization": "Bearer demo-coordinator"}
OTHER = {"Authorization": "Bearer other-resident"}


def report_data():
    """Return a valid unverified road observation with an aware observation time."""
    return {
        "category": "road",
        "description": "SIMULATION: A fallen tree obstructs Cedar Crossing.",
        "latitude": 37.76,
        "longitude": -122.46,
        "location": "Cedar Crossing",
        "observed_at": datetime.now(timezone.utc).isoformat(),
    }


def submit(client):
    """Submit through the real endpoint and return the associated internal incident."""
    response = submit_call(client, report_data())
    assert response.status_code == 200, response.text
    return client.get(f"/incidents/{response.json()['incident_id']}", headers=COORDINATOR).json()


def test_end_to_end_call_extraction(system):
    """Keep reviewed source text private while all four validated findings become reviewable."""
    client, factory = system
    incident = submit(client)
    for _ in range(4):
        assert worker.process_one()
    assert not worker.process_one()
    dossier = client.get(f"/incidents/{incident['id']}", headers=COORDINATOR).json()
    assert len(dossier["findings"]) == 4 and dossier["evidence"]
    assert dossier["status"] == "needs_review"
    assert client.get("/reports", headers=COORDINATOR).json()[0]["status"] == "needs_information"


def test_private_reports_and_role_boundaries(system):
    """Prevent role spoofing and non-dispatcher reads across the retired public surface."""
    client, _ = system
    incident = submit(client)
    report = client.get("/reports", headers=COORDINATOR).json()[0]
    for path in ["/reports", f"/reports/{report['id']}", "/calls", "/incidents",
                 f"/incidents/{incident['id']}", "/agents", "/activity", "/simulation",
                 "/response-plans", "/hospitals", "/vehicles", "/dispatches", "/communications",
                 "/resource-requests", "/resources"]:
        assert client.get(path, headers=RESIDENT).status_code == 403
    assert client.get("/incidents", headers={"X-Role": "coordinator"}).status_code == 401
    for path in ["/updates", "/subscriptions", "/assistant"]:
        assert client.get(path, headers=COORDINATOR).status_code == 404
    assert client.post("/reports", headers=RESIDENT, json=report_data()).status_code == 405
    assert client.post(f"/incidents/{incident['id']}/actions", headers=RESIDENT,
        json={"action": "verify", "version": 1, "note": "Spoofed approval"}).status_code == 403


def test_status_transitions_and_optimistic_concurrency(system):
    """Reject unsupported transitions and stale human review versions."""
    client, _ = system
    incident = submit(client)
    path = f"/incidents/{incident['id']}/actions"
    assert (
        client.post(
            path, headers=COORDINATOR, json={"action": "resolve", "version": 1, "note": "Too early"}
        ).status_code
        == 409
    )
    assert (
        client.post(
            path,
            headers=COORDINATOR,
            json={"action": "verify", "version": incident["version"], "note": "Evidence checked"},
        ).status_code
        == 200
    )
    assert (
        client.post(
            path, headers=COORDINATOR, json={"action": "dispute", "version": 1, "note": "Stale decision"}
        ).status_code
        == 409
    )
    current = client.get(f"/incidents/{incident['id']}", headers=COORDINATOR).json()
    assert (
        client.post(
            path,
            headers=COORDINATOR,
            json={"action": "resolve", "version": current["version"], "note": "Exercise resolved"},
        ).status_code
        == 200
    )


def test_agent_schema_rejects_authority_and_bad_confidence():
    """Reject authority fields and invalid injury values outside the intake contract."""
    payload = {
        "agent_input": {
            "incident_id": "source-1",
            "description": report_data()["description"],
            "location": report_data()["location"],
            "reported_injuries": None,
        }
    }
    valid = MockAdapter().invoke("intake", payload).model_dump()
    assert valid == MockAdapter().invoke("intake", payload).model_dump()
    with pytest.raises(ValidationError):
        Assessment.model_validate({**valid, "official_status": "verified"})
    with pytest.raises(ValidationError):
        Assessment.model_validate({**valid, "reported_injuries": -9})


def test_unknown_agent_evidence_fails_closed(system, monkeypatch):
    """A valid-looking agent output cannot cite evidence outside the provided context."""
    client, _ = system
    incident = submit(client)

    class BadAdapter:
        """Return a fabricated citation to test semantic evidence validation."""

        def invoke(self, stage, payload):
            result = MockAdapter().invoke(stage, payload)
            result.incident_id = "fabricated-source"
            return result

    monkeypatch.setattr(worker, "get_adapter", lambda: BadAdapter())
    worker.process_one()
    assert client.get("/agents", headers=COORDINATOR).json()[0]["status"] == "failed"
    assert client.get(f"/incidents/{incident['id']}", headers=COORDINATOR).json()["status"] == "needs_review"


def test_resource_visibility_capacity_and_double_approval(system):
    """Ensure private resources stay private and approved capacity cannot be consumed twice."""
    client, factory = system
    incident = submit(client)
    with factory() as db:
        resource = Resource(
            name="Private shelter",
            category="shelter",
            location="Exercise",
            latitude=0,
            longitude=0,
            capacity=10,
            occupancy=5,
            published=False,
        )
        db.add(resource)
        db.commit()
        resource_id = resource.id
    assert client.get("/resources", headers=RESIDENT).status_code == 403
    proposal = client.post(
        "/resource-requests",
        headers=COORDINATOR,
        json={
            "incident_id": incident["id"],
            "resource_id": resource_id,
            "quantity": 3,
            "rationale": "Exercise reservation",
        },
    ).json()
    path = f"/resource-requests/{proposal['id']}/approve"
    assert client.post(path, headers=RESIDENT).status_code == 403
    assert client.post(path, headers=COORDINATOR).status_code == 200
    assert client.post(path, headers=COORDINATOR).status_code == 409
    proposal = client.post(
        "/resource-requests",
        headers=COORDINATOR,
        json={
            "incident_id": incident["id"],
            "resource_id": resource_id,
            "quantity": 3,
            "rationale": "Over capacity",
        },
    ).json()
    assert client.post(f"/resource-requests/{proposal['id']}/approve", headers=COORDINATOR).status_code == 409


def test_retired_public_mutations_are_unavailable(system):
    """Removing the portal also removes its public API and assistant capability."""
    client, _ = system
    for path in ["/assistant", "/updates"]:
        assert client.post(path, headers=RESIDENT, json={}).status_code == 404
    assert client.put("/subscriptions/missing", headers=RESIDENT).status_code == 404


def test_demo_credentials_disabled_in_production(system, monkeypatch):
    """Fail closed even if demo credentials remain in a migrated database."""
    client, _ = system
    monkeypatch.setattr(settings, "demo_auth", False)
    assert client.get("/reports", headers=RESIDENT).status_code == 401


@pytest.mark.parametrize("stage", ["intake", "hospital", "dispatch", "planning"])
def test_live_adapter_documented_contract(system, monkeypatch, stage):
    """Verify the documented v1 mapping using a fake transport, without provider credentials."""
    import httpx
    from app.creao import LiveAdapter

    client, factory = system
    submit(client)
    for _ in range(4):
        worker.process_one()
    with factory() as db:
        payload = db.scalar(select(AgentRun).where(AgentRun.stage == stage)).input
    expected = MockAdapter().invoke(stage, payload)
    captured = []

    def handler(request):
        """Assert v1 request names and supply a documented result envelope."""
        import json

        captured.append(request)
        assert request.headers["authorization"] == "Bearer test-key"
        if request.method == "POST":
            body = json.loads(request.content)
            assert body["appId"] == f"{stage}-app"
            assert "context" in body["inputs"]
            assert json.loads(body["inputs"]["context"]) == payload["agent_input"]
            assert body["idempotencyKey"].startswith("kontrol-")
            return httpx.Response(202, json={"id": "remote-run", "status": "pending"})
        result_fields = {
            "intake": {"text": expected.model_dump_json()},
            "hospital": {"chatText": f"```json\n{expected.model_dump_json()}\n```"},
            "dispatch": {"output": expected.model_dump()},
            "planning": {"data": expected.model_dump()},
        }
        return httpx.Response(200, json={"status": "completed", "result": result_fields[stage]})

    original = httpx.Client
    monkeypatch.setattr(settings, "creao_base_url", "https://creao.test")
    monkeypatch.setattr(settings, "creao_api_key", "test-key")
    monkeypatch.setattr(settings, "creao_api_version", "v1")
    monkeypatch.setattr(settings, f"creao_{stage}_agent_id", f"{stage}-app")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert LiveAdapter().invoke(stage, payload) == expected
    assert captured[0].url.path == "/api/v1/runs"
    assert captured[1].url.path == "/api/v1/runs/remote-run"


def test_live_adapter_uses_schema_valid_chat_text(system, monkeypatch):
    """Use CREAO's documented chatText when text contains an intermediate result shape."""
    import httpx
    from app.creao import LiveAdapter

    client, factory = system
    submit(client)
    worker.process_one()
    with factory() as db:
        payload = db.scalar(select(AgentRun).where(AgentRun.stage == "intake")).input
    expected = MockAdapter().invoke("intake", payload)

    def handler(request):
        """Return both documented text fields with only chatText matching the contract."""
        if request.method == "POST":
            return httpx.Response(202, json={"id": "remote-run", "status": "pending"})
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "result": {
                    "text": '{"incident_type":"collision","status":"success"}',
                    "chatText": expected.model_dump_json(),
                },
            },
        )

    original = httpx.Client
    monkeypatch.setattr(settings, "creao_base_url", "https://creao.test")
    monkeypatch.setattr(settings, "creao_api_key", "test-key")
    monkeypatch.setattr(settings, "creao_api_version", "v1")
    monkeypatch.setattr(settings, "creao_intake_agent_id", "intake-app")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert LiveAdapter().invoke("intake", payload) == expected


def test_live_adapter_prefers_json_artifact(system, monkeypatch):
    """Load the canonical agent output artifact when inline text is only a status summary."""
    import httpx
    from app.creao import LiveAdapter

    client, factory = system
    submit(client)
    worker.process_one()
    with factory() as db:
        payload = db.scalar(select(AgentRun).where(AgentRun.stage == "intake")).input
    expected = MockAdapter().invoke("intake", payload)

    def handler(request):
        """Model the observed CREAO envelope and authenticated artifact download."""
        if request.method == "POST":
            return httpx.Response(202, json={"id": "remote-run", "status": "pending"})
        if request.url.path.endswith("/artifact.json"):
            return httpx.Response(200, json=expected.model_dump())
        return httpx.Response(
            200,
            json={
                "status": "completed",
                "result": {
                    "text": '{"incident_type":"vehicle_collision","status":"success"}',
                    "chatText": "The structured result is attached.",
                    "artifacts": [
                        {
                            "type": "application/json",
                            "title": "incident.json",
                            "url": "https://creao.test/artifact.json",
                        }
                    ],
                },
            },
        )

    original = httpx.Client
    monkeypatch.setattr(settings, "creao_base_url", "https://creao.test")
    monkeypatch.setattr(settings, "creao_api_key", "test-key")
    monkeypatch.setattr(settings, "creao_api_version", "v1")
    monkeypatch.setattr(settings, "creao_intake_agent_id", "intake-app")
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert LiveAdapter().invoke("intake", payload) == expected


def test_live_adapter_reuses_run_and_backs_off_on_rate_limit(system, monkeypatch):
    """Resume a completed CREAO run after a transient polling rate limit without another POST."""
    import httpx
    from app.creao import LiveAdapter

    client, factory = system
    submit(client)
    worker.process_one()
    with factory() as db:
        payload = db.scalar(select(AgentRun).where(AgentRun.stage == "intake")).input
    payload = {**payload, "remote_id": "existing-run"}
    expected = MockAdapter().invoke("intake", payload)
    calls = []

    def handler(request):
        """Rate-limit the first poll and complete the existing run on the second."""
        calls.append(request)
        assert request.method == "GET"
        if len(calls) == 1:
            return httpx.Response(429, headers={"Retry-After": "1"})
        return httpx.Response(
            200,
            json={"status": "completed", "result": {"text": expected.model_dump_json()}},
        )

    original = httpx.Client
    monkeypatch.setattr(settings, "creao_base_url", "https://creao.test")
    monkeypatch.setattr(settings, "creao_api_key", "test-key")
    monkeypatch.setattr(settings, "creao_api_version", "v1")
    monkeypatch.setattr(settings, "creao_intake_agent_id", "intake-app")
    monkeypatch.setattr("app.creao.time.sleep", lambda _: None)
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert LiveAdapter().invoke("intake", payload) == expected
    assert len(calls) == 2


def test_live_seed_queue_guard(system, monkeypatch):
    """Starting in live mode must never automatically process the seeded paid batch."""
    from app.models import Report

    client, factory = system
    submit(client)
    with factory() as db:
        db.scalar(select(Report)).source = "simulation"
        db.commit()
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "live_simulation_enabled", False)
    assert worker.process_one() is False


def test_replay_controls_preserve_observations(system):
    """Replay shares normal ingestion and reset never erases report provenance."""
    from app.models import Simulation, Call
    from app.seed import simulation_tick
    from app.db import now
    from datetime import timedelta

    client, factory = system
    with factory() as db:
        db.scalar(select(Simulation)).last_event_at = now() - timedelta(minutes=1)
        db.commit()
    assert client.post("/simulation", headers=RESIDENT, json={"action": "start"}).status_code == 403
    assert client.post("/simulation", headers=COORDINATOR, json={"action": "start"}).status_code == 200
    with factory() as db:
        state = db.scalar(select(Simulation))
        simulation_tick(db, state)
        db.commit()
        assert state.cursor == 1
        assert db.scalar(select(Call)).status == "queued"
        assert not db.scalar(select(AgentRun))
    assert client.post("/simulation", headers=COORDINATOR, json={"action": "reset"}).json()["cursor"] == 0
    assert len(client.get("/calls", headers=COORDINATOR).json()) == 1
