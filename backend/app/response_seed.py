"""Explicit fallback-workflow reset controls."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import now
from .models import (
    AgentRun,
    Call,
    CoordinatorAction,
    DispatchAssignment,
    EmergencyVehicle,
    Incident,
    ResponsePlan,
    Simulation,
    User,
)
from .network import operation_lock
from .response_services import update_response_status

def reset_response_demo(db: Session, user: User) -> None:
    """Cancel simulated work and restore network baselines while retaining provenance and audit history."""
    operation_lock(db)
    state = db.scalar(select(Simulation))
    state.running, state.cursor, state.last_event_at = False, 0, now()
    for plan in db.scalars(
        select(ResponsePlan).where(
            ResponsePlan.simulation.is_(True), ResponsePlan.status.not_in(["rejected", "cancelled"])
        )
    ):
        plan.status = "cancelled"
        plan.decision_note = "SIMULATION reset by coordinator; historical records retained."
        update_response_status(db, db.get(Incident, plan.incident_id), "cancelled")
    for call in db.scalars(select(Call).where(Call.simulation.is_(True), Call.status.not_in(["confirmed", "deleted"]))):
        call.status, call.claim_token, call.lease_expires_at = "failed", None, None
        call.attempts = 3
        call.transcription_error = "Exercise reset. Load a new sample call."
    for run in db.scalars(
        select(AgentRun).where(
            AgentRun.plan_id.in_(select(ResponsePlan.id).where(ResponsePlan.simulation.is_(True))), AgentRun.status.in_(["queued", "running", "failed"])
        )
    ):
        run.status, run.error, run.completed_at = "cancelled", "SIMULATION reset", now()
    for assignment in db.scalars(select(DispatchAssignment).where(DispatchAssignment.released_at.is_(None), DispatchAssignment.plan_id.in_(select(ResponsePlan.id).where(ResponsePlan.simulation.is_(True))))):
        assignment.status, assignment.released_at = "cancelled", now()
    for vehicle in db.scalars(select(EmergencyVehicle).where(EmergencyVehicle.simulation.is_(True))):
        vehicle.status = "available"
        vehicle.latitude, vehicle.longitude, vehicle.location = (
            vehicle.home_latitude,
            vehicle.home_longitude,
            vehicle.home_location,
        )
    db.add(
        CoordinatorAction(
            user_id=user.id,
            action="response_demo_reset",
            details="SIMULATION: Cancelled exercise responses and released exercise fleet assignments. Reports and plans retained.",
        )
    )
