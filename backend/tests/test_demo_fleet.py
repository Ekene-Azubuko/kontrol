"""Verify the fleet-only opt-in and authoritative availability sent to live agents."""

import json
import httpx
import pytest
from sqlalchemy import select
from app import worker
from app.config import settings
from app.creao import LiveAdapter
from app.demo_fleet import FLEET_IDS, seed_demo_fleet
from app.models import AgentRun, EmergencyVehicle
from test_response import generated_plan
from test_workflow import COORDINATOR


def test_demo_fleet_is_opt_in_and_preserves_availability(system, monkeypatch):
    """Expose just the six demo units in live mode without resetting busy vehicles on startup."""
    client, factory = system
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "demo_fleet_enabled", False)
    assert client.get("/vehicles", headers=COORDINATOR).json() == []
    monkeypatch.setattr(settings, "demo_fleet_enabled", True)
    with factory() as db:
        seed_demo_fleet(db)
        unit = db.get(EmergencyVehicle, FLEET_IDS["AMB-01"])
        unit.status = "assigned"
        unit.latitude = 37.78
        seed_demo_fleet(db)
        db.commit()
    fleet = client.get("/vehicles", headers=COORDINATOR).json()
    assert len(fleet) == 6
    unit = next(v for v in fleet if v["id"] == FLEET_IDS["AMB-01"])
    assert unit["status"] == "assigned" and unit["latitude"] == 37.78
    assert client.get("/hospitals", headers=COORDINATOR).json() == []
    monkeypatch.setattr(settings, "demo_fleet_enabled", False)
    assert client.get("/vehicles", headers=COORDINATOR).json() == []


def test_live_dispatch_receives_available_demo_units_only(system, monkeypatch):
    """Keep old exercise resources and busy units out of live input snapshots."""
    client, factory = system
    plan = generated_plan(client)
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "demo_fleet_enabled", True)
    with factory() as db:
        seed_demo_fleet(db)
        db.get(EmergencyVehicle, FLEET_IDS["AMB-01"]).status = "assigned"
        db.flush()
        run = db.scalar(select(AgentRun).where(AgentRun.plan_id == plan["id"], AgentRun.stage == "dispatch"))
        payload = worker.job_payload(db, run)
        fleet = payload["agent_input"]["available_vehicles"]
        assert len(fleet) == 5
        assert {v["vehicle_id"] for v in fleet} == set(FLEET_IDS.values()) - {FLEET_IDS["AMB-01"]}
        assert {v["type"] for v in fleet} == {"ambulance", "police", "fire_engine", "rescue_unit"}
        assert all(v["current_latitude"] and v["current_longitude"] and v["capabilities"] for v in fleet)
        assert "hospitals" not in payload


@pytest.mark.parametrize("stage", ["intake", "hospital", "dispatch", "planning"])
def test_fleet_only_reaches_dispatch_http_request(system, monkeypatch, stage):
    """Inspect actual CREAO POST bodies with demo fleet enabled for every stage."""
    client, factory = system
    plan = generated_plan(client)
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "demo_fleet_enabled", True)
    with factory() as db:
        seed_demo_fleet(db)
        run = db.scalar(select(AgentRun).where(AgentRun.plan_id == plan["id"], AgentRun.stage == stage))
        expected_output = run.output
        if stage in {"intake", "hospital"}:
            def unexpected_fleet_read(*args, **kwargs):
                """Ensure these stages cannot fail because of a fleet database read."""
                raise AssertionError("This stage must not read the vehicle fleet")

            monkeypatch.setattr(worker, "vehicles", unexpected_fleet_read)
        payload = worker.job_payload(db, run)
    if stage in {"intake", "hospital"}:
        assert "vehicles" not in payload
    keys = {
        "intake": {"incident_id", "transcript", "confirmed_location", "call_received_at", "category"},
        "hospital": {"incident_id", "incident_type", "incident_location", "reported_injuries",
                     "required_hospital_capabilities", "search_radius_miles", "hospital_statuses"},
        "dispatch": {"incident_id", "incident_type", "incident_location", "required_response_types",
                     "search_radius_miles", "available_vehicles"},
        "planning": {"incident_id", "intake_result", "hospital_result", "dispatch_result"},
    }
    sent = []

    def handler(request):
        """Record the wire context without making any real provider calls."""
        if request.method == "POST":
            context = json.loads(json.loads(request.content)["inputs"][settings.creao_input_field])
            sent.append(context)
            assert set(context) == keys[stage]
            if stage == "dispatch":
                assert {v["vehicle_id"] for v in context["available_vehicles"]} == set(FLEET_IDS.values())
            else:
                assert "available_vehicles" not in json.dumps(context)
                assert "patient_capacity" not in json.dumps(context)
            return httpx.Response(202, json={"id": "test-run"})
        return httpx.Response(200, json={"status": "completed", "result": {"output": expected_output}})

    original_client = httpx.Client
    monkeypatch.setattr(settings, "creao_base_url", "https://creao.test")
    monkeypatch.setattr(settings, "creao_api_key", "test-key")
    monkeypatch.setattr(settings, "creao_api_version", "v1")
    monkeypatch.setattr(settings, f"creao_{stage}_agent_id", f"{stage}-app")
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    LiveAdapter().invoke(stage, payload)
    assert len(sent) == 1
