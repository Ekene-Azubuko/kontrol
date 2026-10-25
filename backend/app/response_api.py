"""Coordinator-only operational endpoints for response plans and the simulation network."""

from fastapi import APIRouter, HTTPException
from sqlalchemy import select
from .config import settings
from .demo_fleet import vehicle_enabled
from .db import now
from .dependencies import DB, Coordinator
from .models import (
    AgentRun,
    Call,
    CommunicationLog,
    CoordinatorAction,
    DispatchAssignment,
    EmergencyVehicle,
    Hospital,
    Incident,
    IncidentReport,
    ProposedAssignment,
    Report,
    ResponsePlan,
)
from .network import hospitals, operation_lock, record, vehicles
from .response_schemas import DemoControl, GeneratePlan, PlanDecision
from .response_services import create_plan, decide_plan
from .services import require_record

router = APIRouter()


def plan_record(db, plan: ResponsePlan) -> dict:
    """Present the proposal with named resources, explanations and actual execution records."""
    from .call_services import call_record

    # Provider selection controls new execution, never access to persisted exercise history.
    assignments = []
    for row in db.scalars(select(ProposedAssignment).where(ProposedAssignment.plan_id == plan.id)):
        vehicle = db.get(EmergencyVehicle, row.vehicle_id)
        hospital = db.get(Hospital, row.hospital_id) if row.hospital_id else None
        assignments.append(
            {
                **record(row),
                "vehicle": record(vehicle),
                "hospital": record(hospital) if hospital else None,
            }
        )
    return {
        **record(plan),
        "incident": record(db.get(Incident, plan.incident_id)),
        "report_source": db.get(Report, plan.report_id).source,
        "call": (call_record(db, call) if (call := db.scalar(select(Call).where(Call.report_id == plan.report_id, Call.status != "deleted"))) else None),
        "assignments": assignments,
        "runs": [
            record(r)
            for r in db.scalars(
                select(AgentRun).where(AgentRun.plan_id == plan.id).order_by(AgentRun.created_at)
            )
        ],
        "dispatches": [
            record(r)
            for r in db.scalars(select(DispatchAssignment).where(DispatchAssignment.plan_id == plan.id))
        ],
    }


@router.get("/response-plans")
def response_plans(db: DB, user: Coordinator, incident_id: str | None = None):
    """List operational plans, optionally scoped to an existing incident."""
    query = (
        select(ResponsePlan)
        .order_by(ResponsePlan.created_at.desc())
    )
    if incident_id:
        require_record(db, Incident, incident_id)
        query = query.where(ResponsePlan.incident_id == incident_id)
    return [plan_record(db, plan) for plan in db.scalars(query.limit(100))]


@router.get("/response-plans/{plan_id}")
def response_plan(plan_id: str, db: DB, user: Coordinator):
    """Return a private plan dossier only after coordinator authorization."""
    plan = require_record(db, ResponsePlan, plan_id)
    return plan_record(db, plan)


@router.post("/response-plans/{plan_id}/decision")
def decision(plan_id: str, data: PlanDecision, db: DB, user: Coordinator):
    """Make reservations and simulated messages part of the same human-decision transaction."""
    require_record(db, ResponsePlan, plan_id)
    result = decide_plan(db, plan_id, user, data)
    db.commit()
    return plan_record(db, result)


@router.post("/incidents/{incident_id}/plan", status_code=201)
def generate_plan(incident_id: str, data: GeneratePlan, db: DB, user: Coordinator):
    """Start a manually requested workflow for an unplanned or rejected incident."""
    operation_lock(db)
    require_record(db, Incident, incident_id)
    incident = db.scalar(select(Incident).where(Incident.id == incident_id).with_for_update())
    report = db.scalar(
        select(Report)
        .join(IncidentReport, IncidentReport.report_id == Report.id)
        .where(IncidentReport.incident_id == incident_id)
        .order_by(Report.created_at.desc())
    )
    if not report:
        raise HTTPException(409, "An original report is required to generate a plan")
    plan = create_plan(db, incident, report, data.note)
    db.add(
        CoordinatorAction(user_id=user.id, incident_id=incident.id, action="plan_generate", details=data.note)
    )
    db.commit()
    return plan_record(db, plan)


@router.get("/hospitals")
def hospital_network(db: DB, user: Coordinator, incident_id: str | None = None):
    """Expose only live hospital records to frontend clients."""
    rows = hospitals(db, require_record(db, Incident, incident_id) if incident_id else None)
    return [row for row in rows if not row["simulation"]] if settings.creao_mode == "live" and not settings.live_simulation_enabled else rows


@router.get("/vehicles")
def fleet(db: DB, user: Coordinator, incident_id: str | None = None):
    """Expose current vehicle states and assignments exclusively to coordinators."""
    rows = vehicles(db, require_record(db, Incident, incident_id) if incident_id else None)
    return [row for row in rows if vehicle_enabled(row["id"], row["simulation"])]


@router.get("/dispatches")
def dispatches(db: DB, user: Coordinator):
    """Return dispatch history for live response plans only."""
    result = []
    query = (
        select(DispatchAssignment)
        .join(ResponsePlan, ResponsePlan.id == DispatchAssignment.plan_id)
        .order_by(DispatchAssignment.created_at.desc())
        .limit(100)
    )
    for row in db.scalars(query):
        vehicle = db.get(EmergencyVehicle, row.vehicle_id)
        hospital = db.get(Hospital, row.hospital_id) if row.hospital_id else None
        result.append(
            {
                **record(row),
                "vehicle": record(vehicle),
                "incident": record(db.get(Incident, row.incident_id)),
                "hospital": record(hospital) if hospital else None,
            }
        )
    return result


@router.get("/communications")
def communications(db: DB, user: Coordinator):
    """Read internal messages associated with live responses."""
    query = select(CommunicationLog).order_by(CommunicationLog.created_at.desc()).limit(200)
    return [
        {**record(row), "incident_title": db.get(Incident, row.incident_id).title}
        for row in db.scalars(query)
    ]


@router.post("/communications/{message_id}/acknowledge")
def acknowledge(message_id: str, db: DB, user: Coordinator):
    """Record an explicit simulated acknowledgement without sending a real message."""
    row = require_record(db, CommunicationLog, message_id)
    if row.status != "acknowledged":
        row.status, row.acknowledged_at = "acknowledged", now()
        db.add(
            CoordinatorAction(
                user_id=user.id,
                incident_id=row.incident_id,
                action="message_acknowledged",
                details=f"SIMULATION: Acknowledged message {row.id}",
            )
        )
        db.commit()
    return record(row)


@router.post("/response-demo")
def response_demo(data: DemoControl, db: DB, user: Coordinator):
    """Start a prepared report or reset only this explicitly simulated exercise."""
    from .response_seed import reset_response_demo

    if not settings.demo_auth or settings.app_env == "production":
        raise HTTPException(403, "Demo controls are disabled")
    operation_lock(db)
    if data.action == "reset":
        reset_response_demo(db, user)
        db.commit()
        return {"status": "reset", "simulation": True}
    if settings.creao_mode == "live" and not settings.live_simulation_enabled:
        raise HTTPException(409, "Prepared demo reports require LIVE_SIMULATION_ENABLED in live mode")
    from .call_api import sample_call

    return sample_call("collision", db, user)
