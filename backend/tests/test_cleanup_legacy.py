"""Protect actual call provenance while retiring the old exercise dataset."""

from sqlalchemy import func, select
from app import worker
from app.cleanup_legacy import cleanup_legacy
from app.models import AgentRun, Call, CommunicationLog, Hospital, HospitalInventory, Report, ResponsePlan
from app.seed import seed
from call_helpers import submit_call
from test_response import decide, generated_plan
from test_workflow import COORDINATOR, report_data


def test_cleanup_preserves_real_call_workflow_and_resets_sample_links(system):
    """Remove old test dependencies without dangling call links or deleting a real call's queue item."""
    client, factory = system
    old_plan = generated_plan(client)
    actual = submit_call(client, report_data()).json()
    with factory() as db:
        call = db.scalar(select(Call).where(Call.report_id == actual["report_id"]))
        call.source, call.sample_key, call.simulation = "live", None, False
        call_id = call.id
        db.get(Report, actual["report_id"]).simulation = False
        db.commit()
        counts = cleanup_legacy(db)
        db.commit()
        assert counts["hospital_inventory"] == 18
        assert counts["emergency_vehicles"] == 10
        assert db.get(ResponsePlan, old_plan["id"]) is None
        assert db.get(Call, call_id).report_id == actual["report_id"]
        assert db.get(Report, actual["report_id"])
        assert db.scalar(select(func.count()).select_from(AgentRun)) == 1
        assert all(c.report_id is None or c.id == call_id for c in db.scalars(select(Call)))
        assert all(count == 0 for count in cleanup_legacy(db).values())
        db.commit()


def test_clean_start_has_no_hospital_inventory_and_offline_demo_can_be_approved(system):
    """A fresh install creates only the small fleet and completes all agent stages without bed fiction."""
    client, factory = system
    with factory() as db:
        cleanup_legacy(db)
        seed(db)
        assert db.scalar(select(func.count()).select_from(Hospital)) == 0
        assert db.scalar(select(func.count()).select_from(HospitalInventory)) == 0
    fleet = client.get("/vehicles", headers=COORDINATOR).json()
    assert len(fleet) == 6 and all(not v["call_sign"].startswith("SIM-") for v in fleet)
    result = submit_call(client, report_data())
    assert result.status_code == 200
    for _ in range(4):
        assert worker.process_one()
    plan = client.get("/response-plans", headers=COORDINATOR).json()[0]
    assert plan["status"] == "needs_information"
    approved = decide(client, plan)
    assert approved.status_code == 200, approved.text
    assert approved.json()["status"] == "approved"
    with factory() as db:
        assert not db.scalar(select(CommunicationLog))
        assert all(h.total_beds is None and h.occupied_beds is None and h.diversion is None and h.reserved_beds == 0 for h in db.scalars(select(Hospital)))


def test_cleanup_retires_old_fleet_response_but_keeps_live_call_source(system):
    """A live call attached to a deprecated SIM response returns to review with its transcript intact."""
    client, factory = system
    plan = generated_plan(client)
    with factory() as db:
        call = db.scalar(select(Call).where(Call.report_id == plan["report_id"]))
        call.source, call.sample_key, call.simulation = "live", None, False
        call_id, original = call.id, call.original_transcript
        db.commit()
        counts = cleanup_legacy(db)
        db.commit()
        assert counts["emergency_vehicles"] == 10
        assert db.get(ResponsePlan, plan["id"]) is None
        call = db.get(Call, call_id)
        assert call.report_id is None and call.status == "awaiting_review"
        assert call.original_transcript == original
