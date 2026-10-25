"""Explicitly load one prepared judging scenario without invoking external providers."""

from uuid import NAMESPACE_URL, uuid5
from fastapi.encoders import jsonable_encoder
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import SessionLocal, now
from .demo_fleet import FLEET_IDS, seed_demo_fleet, vehicle_enabled
from .models import AgentRun, CoordinatorAction, EmergencyVehicle, Evidence, Incident, IncidentReport, Report, ResponsePlan, User
from .network import operation_lock
from .response_schemas import stage_schema
from .response_services import validate_stage
from .worker import finish_stage, job_payload

PLAN_ID = str(uuid5(NAMESPACE_URL, "kontrol:prepared-judging-plan:market-8th:v1"))
NOTICE = "SIMULATION / NOT FOR EMERGENCY USE. Prepared judging scenario; no live agent execution or dispatch."
HOSPITAL = "Zuckerberg San Francisco General Hospital and Trauma Center"


def load_prepared_plan(db: Session) -> ResponsePlan:
    """Create one reviewable plan atomically, preserving its decision on subsequent loads."""
    operation_lock(db)
    existing = db.get(ResponsePlan, PLAN_ID)
    if existing:
        return existing
    user = db.scalar(select(User).where(User.role == "coordinator"))
    if not user:
        raise ValueError("Initialize the app with python -m app.seed first")
    seed_demo_fleet(db)
    units = [db.get(EmergencyVehicle, FLEET_IDS[name]) for name in ["AMB-01", "POL-01"]]
    if any(not unit or unit.status != "available" or not vehicle_enabled(unit.id, unit.simulation) for unit in units):
        raise ValueError("Enable the demo fleet and make AMB-01 and POL-01 available before loading this plan")
    description = (
        "Two vehicles collided at Market Street and 8th Street, San Francisco. "
        "One person is reported injured and conscious. Both vehicles are stationary. "
        "No fire, smoke, hazardous materials or entrapment are reported."
    )
    incident = Incident(
        title="Market & 8th · Vehicle collision", category="vehicle_collision", severity="moderate",
        latitude=37.7787, longitude=-122.4148, location="Market Street & 8th Street, San Francisco, CA",
        summary=description, reported_casualties=1, simulation=True,
    )
    db.add(incident)
    report = Report(
        user_id=user.id, source="prepared_demo", category="collision", description=f"{NOTICE}\n{description}",
        reported_casualties=1, latitude=incident.latitude, longitude=incident.longitude,
        location=incident.location, observed_at=now(), simulation=True,
    )
    db.add(report)
    db.flush()
    db.add(IncidentReport(incident_id=incident.id, report_id=report.id))
    plan = ResponsePlan(id=PLAN_ID, incident_id=incident.id, report_id=report.id, simulation=True,
                        revision_note="Prepared judging scenario, loaded explicitly", constraints=[NOTICE])
    db.add(plan)
    db.flush()
    db.add(AgentRun(plan_id=plan.id, incident_id=incident.id, report_id=report.id, stage="intake"))
    db.flush()
    outputs = {
        "intake": {
            "incident_id": report.id, "incident_type": "vehicle_collision", "summary": description,
            "reported_injuries": 1, "required_response_types": ["ambulance", "police"],
            "reasoning": "Prepared example: medical assessment for the reported injury and police scene/traffic control.",
            "limitations": [NOTICE, "The resident account and injury count are unverified."],
        },
        "hospital": {
            "incident_id": report.id,
            "hospitals": [{
                "name": HOSPITAL, "address": "1001 Potrero Avenue, San Francisco, CA 94110",
                "latitude": 37.7568103, "longitude": -122.4052532,
                "documented_capabilities": ["emergency_department", "trauma"],
                "available_beds": None, "diversion_status": None,
                "estimated_travel_minutes": None, "travel_time_method": "unavailable",
                "source_urls": ["https://zsfg.ucsf.edu/"],
                "suitability_notes": "Reference destination for this prepared scenario; acceptance and bed capacity are unconfirmed.",
            }],
            "recommended_hospitals": [HOSPITAL],
            "reasoning": "Prepared reference destination with emergency and trauma services; this is not a live availability check.",
            "limitations": ["Hospital acceptance, beds and diversion status must be confirmed; no capacity is invented."],
        },
        "dispatch": {
            "incident_id": report.id, "discovered_facilities": [],
            "recommended_vehicles": [{
                "vehicle_id": unit.id, "response_role": role, "starting_location": unit.location,
                "estimated_arrival_minutes": None,
                "reasoning": reason,
            } for unit, role, reason in zip(units, ["ambulance", "police"], [
                "AMB-01 provides the prepared patient assessment and transport assignment.",
                "POL-01 provides the prepared scene safety and traffic-control assignment.",
            ])],
            "unfilled_requirements": [],
            "reasoning": "The two existing demo units cover the requested response roles.",
            "limitations": ["Vehicle locations and any coordinate travel estimates are illustrative demo inputs."],
        },
        "planning": {
            "incident_id": report.id,
            "plan_summary": "Send AMB-01 for the reported injured person and POL-01 for scene and traffic control at Market & 8th. Propose ZSFG as the receiving destination, subject to confirmation.",
            "hospital_assignments": [{"hospital_name": HOSPITAL, "planned_patient_count": 1,
                                      "reasoning": "Provisional receiving destination for the prepared casualty."}],
            "vehicle_assignments": [{"vehicle_id": unit.id, "response_role": role, "destination": destination,
                                     "reasoning": reason} for unit, role, destination, reason in zip(
                units, ["ambulance", "police"], [HOSPITAL, "incident location"],
                ["Assess the reported casualty; proposed transport awaits destination confirmation.",
                 "Support scene safety and traffic control at the reported collision."])],
            "unfilled_requirements": [], "constraints": [NOTICE, "Hospital capacity and acceptance remain unknown."],
            "reasoning": "Prepared proposal combines the example intake, hospital destination and existing demo fleet for coordinator review.",
            "status": "awaiting_approval",
        },
    }
    # Finish all four stages within this transaction so the worker never claims these prepared jobs.
    # Validating through the normal contracts keeps the demo compatible with real plan review and approval.
    for stage in ["intake", "hospital", "dispatch", "planning"]:
        db.flush()
        run = db.scalar(select(AgentRun).where(AgentRun.plan_id == plan.id, AgentRun.stage == stage))
        run.input = jsonable_encoder(job_payload(db, run))
        output = stage_schema(stage).model_validate(outputs[stage]).model_dump(mode="json")
        validate_stage(stage, output, run.input)
        run.started_at = now()
        run.raw_response = {"source": "prepared_demo", "notice": NOTICE, "output": output}
        finish_stage(db, run, output)
    # Queue placement does not establish hospital capacity; use existing constrained human approval.
    plan.feasible = False
    for evidence in db.scalars(select(Evidence).where(Evidence.report_id == report.id)):
        evidence.source = "prepared judging scenario"
    db.add(CoordinatorAction(user_id=user.id, incident_id=incident.id, action="prepared_plan_loaded", details=NOTICE))
    db.flush()
    return plan


if __name__ == "__main__":
    with SessionLocal() as session:
        plan = load_prepared_plan(session)
        session.commit()
        print(f"Prepared plan {plan.id}: {plan.status}")
