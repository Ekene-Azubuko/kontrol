"""Exercise the approval boundary, resource constraints, revisions and dispatch lifecycle."""

from datetime import timedelta
import pytest
from sqlalchemy import select
from app import worker
from call_helpers import submit_call
from app.db import now
from app.models import AgentRun, DispatchAssignment, EmergencyVehicle, Hospital, Report
from app.response_services import validate_stage
from test_workflow import RESIDENT, COORDINATOR, report_data  # noqa: F401


def generated_plan(client, casualties=2):
    """Drive a real resident report through all four deterministic worker stages."""
    response = submit_call(client, {**report_data(), "category": "collision", "reported_casualties": casualties},
    )
    assert response.status_code == 200
    for _ in range(4):
        assert worker.process_one()
    plan = client.get("/response-plans", headers=COORDINATOR).json()[0]
    assert plan["status"] in {"awaiting_approval", "needs_information"}
    assert len(plan["runs"]) == 4
    return plan


def decide(client, plan, action="approve"):
    """Submit a version-protected decision through the coordinator API."""
    return client.post(
        f"/response-plans/{plan['id']}/decision",
        headers=COORDINATOR,
        json={
            "action": action,
            "version": plan["version"],
            "note": "Reviewed simulated response requirements",
        },
    )


def test_approval_keeps_static_assignments_without_synthetic_arrivals(system, monkeypatch):
    """A future worker heartbeat must not move approved vehicles, admit patients or auto-complete the plan."""
    client, factory = system
    baseline = client.get("/hospitals", headers=COORDINATOR).json()
    plan = generated_plan(client)
    assert plan["feasible"] and len(plan["assignments"]) == 2
    assert client.get("/dispatches", headers=COORDINATOR).json() == []
    assert client.get("/communications", headers=COORDINATOR).status_code == 404
    assert all(v["status"] == "available" for v in client.get("/vehicles", headers=COORDINATOR).json())
    assert (
        client.post(
            f"/response-plans/{plan['id']}/decision",
            headers=RESIDENT,
            json={"action": "approve", "version": plan["version"], "note": "Unauthorized"},
        ).status_code
        == 403
    )
    approved = decide(client, plan)
    assert approved.status_code == 200, approved.text
    assert decide(client, plan).status_code == 409
    assert sum(h["reserved_beds"] for h in client.get("/hospitals", headers=COORDINATOR).json()) == 0
    assert sum(h["occupied_beds"] for h in client.get("/hospitals", headers=COORDINATOR).json()) == sum(
        h["occupied_beds"] for h in baseline
    )
    assert client.get("/communications", headers=COORDINATOR).status_code == 404
    positions = {v["id"]: (v["latitude"], v["longitude"]) for v in client.get("/vehicles", headers=COORDINATOR).json()}
    with factory() as db:
        for dispatch in db.scalars(select(DispatchAssignment)):
            dispatch.stage_started_at = now() - timedelta(days=1)
        db.commit()

    class StopWorker(BaseException):
        """Stop after one real maintenance iteration without swallowing the test signal."""

    def stop_after_heartbeat(_):
        """Exit before a second heartbeat or any wall-clock waiting."""
        raise StopWorker()

    from app import call_worker, live_worker
    with monkeypatch.context() as patch:
        patch.setattr(worker, "now", lambda: now() + timedelta(days=1))
        patch.setattr(worker, "process_one", lambda: False)
        patch.setattr(call_worker, "process_one_call", lambda: False)
        patch.setattr(live_worker, "live_maintenance", lambda: False)
        patch.setattr(worker.time, "sleep", stop_after_heartbeat)
        with pytest.raises(StopWorker):
            worker.main()
    fleet = client.get("/vehicles", headers=COORDINATOR).json()
    assert {v["id"]: (v["latitude"], v["longitude"]) for v in fleet} == positions
    assignments = client.get("/dispatches", headers=COORDINATOR).json()
    assert all(d["status"] == "assigned" and d["progress"] == 0 and d["released_at"] is None for d in assignments)
    final = client.get("/hospitals", headers=COORDINATOR).json()
    assert sum(h["occupied_beds"] for h in final) == sum(h["occupied_beds"] for h in baseline)
    assert sum(h["reserved_beds"] for h in final) == 0
    assert client.get(f"/response-plans/{plan['id']}", headers=COORDINATOR).json()["status"] == "approved"
    assert client.get("/reports", headers=COORDINATOR).json()[0]["status"] == "assigned"
    assert client.get("/communications", headers=COORDINATOR).status_code == 404
    assert decide(client, approved.json(), "revise").status_code == 409


def test_parallel_barrier_and_no_early_reservations(system):
    """Queue both evaluations together and wait for both before creating exactly one planner job."""
    client, factory = system
    submit_call(client, report_data())
    worker.process_one()
    with factory() as db:
        assert {r.stage for r in db.scalars(select(AgentRun).where(AgentRun.status == "queued"))} == {
            "hospital",
            "dispatch",
        }
    worker.process_one()
    with factory() as db:
        assert not db.scalar(select(AgentRun).where(AgentRun.stage == "planning"))
    worker.process_one()
    with factory() as db:
        assert len(list(db.scalars(select(AgentRun).where(AgentRun.stage == "planning")))) == 1
        assert all(v.status == "available" for v in db.scalars(select(EmergencyVehicle)))
        assert all(h.reserved_beds == 0 for h in db.scalars(select(Hospital)))


def test_revision_rejection_and_reset_keep_history(system):
    """Manual revision creates a new workflow, rejection has no effects and reset preserves provenance."""
    client, factory = system
    first = generated_plan(client)
    assert decide(client, first, "revise").status_code == 200
    for _ in range(4):
        worker.process_one()
    plans = client.get("/response-plans", headers=COORDINATOR).json()
    second = next(p for p in plans if p["revision"] == 2)
    assert next(p for p in plans if p["id"] == first["id"])["status"] == "rejected"
    assert decide(client, second, "reject").status_code == 200
    assert client.get("/communications", headers=COORDINATOR).status_code == 404
    third = generated_plan(client)
    assert decide(client, third).status_code == 200
    assert client.post("/response-demo", headers=RESIDENT, json={"action": "reset"}).status_code == 403
    assert client.post("/response-demo", headers=COORDINATOR, json={"action": "reset"}).status_code == 200
    with factory() as db:
        assert len(list(db.scalars(select(Report)))) == 2
        assert all(v.status == "available" for v in db.scalars(select(EmergencyVehicle)))
        assert all(
            h.reserved_beds == 0 and h.occupied_beds == h.baseline_occupied
            for h in db.scalars(select(Hospital))
        )
    assert client.get("/communications", headers=COORDINATOR).status_code == 404
    assert client.post("/response-demo", headers=COORDINATOR, json={"action": "start"}).status_code == 200


def test_stale_capacity_and_infeasible_plans(system):
    """Recheck current beds at approval and keep an undersupplied plan unapprovable."""
    client, factory = system
    plan = generated_plan(client)
    hospital_id = next(a["hospital_id"] for a in plan["assignments"] if a["hospital_id"])
    with factory() as db:
        db.get(Hospital, hospital_id).diversion = True
        db.commit()
    assert decide(client, plan).status_code == 409
    assert client.get("/dispatches", headers=COORDINATOR).json() == []
    impossible = generated_plan(client, 100)
    assert impossible["status"] == "needs_information" and not impossible["feasible"]
    assert impossible["constraints"]
    assert decide(client, impossible).status_code == 409


def test_double_booking_and_hallucinated_resource_rejected(system):
    """Concurrent proposals may overlap, but the second approval cannot consume the same units."""
    client, factory = system
    first, second = generated_plan(client), generated_plan(client)
    assert decide(client, first).status_code == 200
    assert decide(client, second).status_code == 409
    with factory() as db:
        run = db.scalar(select(AgentRun).where(AgentRun.stage == "hospital"))
        with pytest.raises(ValueError, match="recommendations"):
            validate_stage(
                "hospital",
                {
                    "incident_id": run.input["agent_input"]["incident_id"],
                    "hospitals": [],
                    "recommended_hospitals": ["Invented Hospital"],
                },
                run.input,
            )


def test_constrained_approval_still_rechecks_vehicle_availability(system):
    """Accepting missing information never grants two incidents the same busy vehicle."""
    from app.models import ResponsePlan

    client, factory = system
    plan = generated_plan(client)
    with factory() as db:
        stored = db.get(ResponsePlan, plan["id"])
        stored.status, stored.feasible = "needs_information", False
        db.get(EmergencyVehicle, plan["assignments"][0]["vehicle_id"]).status = "assigned"
        db.commit()
    plan = client.get(f"/response-plans/{plan['id']}", headers=COORDINATOR).json()
    response = decide(client, plan)
    assert response.status_code == 409
    assert "no longer available" in response.json()["detail"]
    assert client.get("/dispatches", headers=COORDINATOR).json() == []


def test_capacity_consumed_between_evaluation_and_planning(system):
    """A newly unavailable fleet produces a constrained plan, without inventing assignments or failing the workflow."""
    client, factory = system
    submit_call(client, {**report_data(), "category": "collision", "reported_casualties": 2},
    )
    for _ in range(3):
        worker.process_one()
    with factory() as db:
        for vehicle in db.scalars(select(EmergencyVehicle)):
            vehicle.status = "assigned"
        db.commit()
    worker.process_one()
    plan = client.get("/response-plans", headers=COORDINATOR).json()[0]
    assert plan["status"] == "needs_information" and not plan["feasible"]
    assert not plan["assignments"] and plan["constraints"]
