"""Exercise the observed rich Planning artifact through validation, storage and coordinator review."""

import json
from pathlib import Path

import pytest
from sqlalchemy import select

from app import worker
from call_helpers import submit_call
from app.config import settings
from app.demo_fleet import seed_demo_fleet
from app.models import AgentRun, Hospital
from app.response_schemas import DispatchResult, HospitalResult, IntakeResult, PlanningResult
from test_creao_artifacts import download_result
from test_workflow import COORDINATOR, RESIDENT, report_data


def planning_artifact() -> dict:
    """Read the exact supplied CREAO artifact rather than a shortened inline summary."""
    return json.loads((Path(__file__).parent / "fixtures" / "planning_needs_information.json").read_text())


def test_full_planning_artifact_preserves_metadata_and_uncertainty():
    """Accept known metadata without dropping nested ETAs, limitations or unknown capacity."""
    artifact = planning_artifact()
    output = download_result("planning", json.dumps(artifact)).model_dump()
    assert output == artifact
    assert output["status"] == "needs_information"
    assert output["planned_patient_count"] is None
    assert output["hospital_assignments"][0]["planned_patient_count"] is None
    assert output["vehicle_assignment_count"] == 4


@pytest.mark.parametrize("existing_capacity,legacy_missing_hospital", [(None, False), (8, False), (None, True)])
def test_planning_artifact_supports_coordinator_approval_with_unknown_capacity(
    system, monkeypatch, existing_capacity, legacy_missing_hospital,
):
    """Approve a constrained response while preserving unknown counts and leaving hospital capacity authoritative."""
    client, factory = system
    artifact = planning_artifact()
    hospital_name = artifact["hospital_assignments"][0]["hospital_name"]
    hospital_address = "1001 Potrero Avenue, San Francisco, CA 94110"
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "live_simulation_enabled", True)
    monkeypatch.setattr(settings, "demo_fleet_enabled", True)
    with factory() as db:
        seed_demo_fleet(db)
        if existing_capacity is not None:
            db.add(Hospital(
                name=hospital_name, location=hospital_address, latitude=37.7557, longitude=-122.4042,
                capabilities=["emergency"], total_beds=existing_capacity, occupied_beds=3,
                baseline_occupied=3, reserved_beds=1, diversion=False, simulation=False,
            ))
        db.commit()

    class ArtifactPipeline:
        """Supply validated upstream results and the real-format Planning artifact without provider calls."""

        def invoke(self, stage: str, payload: dict):
            """Use the job's identity and existing demo fleet to preserve cross-stage validation."""
            agent_input = payload["agent_input"]
            incident_id = agent_input["incident_id"]
            if stage == "intake":
                return IntakeResult(
                    incident_id=incident_id, incident_type="vehicle_collision",
                    summary="Two vehicles collided at Market and 8th; one person is reported injured.",
                    reported_injuries=1, required_response_types=["ambulance", "police"],
                    reasoning="The reported injury and blocked intersection require medical and traffic response.",
                )
            if stage == "hospital":
                return HospitalResult(
                    incident_id=incident_id,
                    hospitals=[{
                        "name": hospital_name, "address": hospital_address,
                        "latitude": 37.7557, "longitude": -122.4042,
                        "documented_capabilities": ["emergency", "trauma"],
                        "available_beds": 999, "diversion_status": None,
                        "estimated_travel_minutes": 6, "travel_time_method": "road_routing",
                        "source_urls": [], "suitability_notes": "Documented trauma capabilities.",
                    }],
                    recommended_hospitals=[hospital_name], reasoning="Nearby documented trauma facility.",
                )
            if stage == "dispatch":
                return DispatchResult(
                    incident_id=incident_id,
                    recommended_vehicles=[{
                        "vehicle_id": row["vehicle_id"], "response_role": row["response_role"],
                        "starting_location": "Configured base",
                        "estimated_arrival_minutes": row["estimated_arrival_minutes"],
                        "reasoning": row["reasoning"],
                    } for row in artifact["vehicle_assignments"]],
                    reasoning="Only supplied available Kontrol units are recommended.",
                )
            return download_result("planning", json.dumps({**artifact, "incident_id": incident_id}))

    monkeypatch.setattr(worker, "get_adapter", ArtifactPipeline)
    response = submit_call(client, {
        **report_data(), "category": "collision", "reported_casualties": 1,
        "description": "Two vehicles collided at Market and 8th; one person is reported injured.",
    })
    assert response.status_code == 200
    for _ in range(3):
        assert worker.process_one()
    if legacy_missing_hospital:
        with factory() as db:
            db.delete(db.scalar(select(Hospital).where(Hospital.name == hospital_name)))
            db.commit()
    assert worker.process_one()
    plan = client.get("/response-plans", headers=COORDINATOR).json()[0]
    assert plan["status"] == "needs_information" and not plan["feasible"]
    assert len(plan["assignments"]) == 4
    destination = next(a for a in plan["assignments"] if a["hospital_id"])
    assert destination["hospital"]["name"] == hospital_name
    assert destination["patients"] is None
    assert set(artifact["limitations"]).issubset(plan["constraints"])
    assert client.get("/dispatches", headers=COORDINATOR).json() == []
    decision = {
        "action": "approve", "version": plan["version"], "note": "Review the constrained proposal",
    }
    assert client.post(f"/response-plans/{plan['id']}/decision", headers=RESIDENT, json=decision).status_code == 403
    approval = client.post(f"/response-plans/{plan['id']}/decision", headers=COORDINATOR, json=decision)
    assert approval.status_code == 200, approval.text
    approved = approval.json()
    assert approved["status"] == "approved"
    assert len(approved["dispatches"]) == 4
    assert any(d["patients"] is None for d in approved["dispatches"])
    assert all(d["reserved_beds"] == 0 for d in approved["dispatches"])
    assert set(artifact["limitations"]).issubset(approved["constraints"])
    assert client.post(f"/response-plans/{plan['id']}/decision", headers=COORDINATOR, json=decision).status_code == 409
    with factory() as db:
        hospital = db.scalar(select(Hospital).where(Hospital.name == hospital_name))
        assert hospital.total_beds == existing_capacity
        assert hospital.occupied_beds == (3 if existing_capacity is not None else None)
        assert hospital.reserved_beds == (1 if existing_capacity is not None else 0)
        run = db.scalar(select(AgentRun).where(AgentRun.plan_id == plan["id"], AgentRun.stage == "planning"))
        assert run.status == "completed" and run.error is None
        assert run.output["planned_patient_count"] is None
        assert run.output["limitations"] == artifact["limitations"]
    persisted = client.get(f"/response-plans/{plan['id']}", headers=COORDINATOR).json()
    assert persisted["status"] == "approved"


@pytest.mark.parametrize("bad_value", [-1, 1441])
def test_planning_artifact_rejects_invalid_vehicle_etas(bad_value):
    """Newly supported ETA metadata remains bounded by the existing travel-time contract."""
    artifact = planning_artifact()
    artifact["vehicle_assignments"][0]["estimated_arrival_minutes"] = bad_value
    with pytest.raises(ValueError):
        PlanningResult.model_validate(artifact)
