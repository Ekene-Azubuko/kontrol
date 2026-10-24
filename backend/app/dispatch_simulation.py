"""Clock-driven, explicitly simulated vehicle movement and hospital arrivals."""

from datetime import datetime
from sqlalchemy import select
from sqlalchemy.orm import Session
from .config import settings
from .db import now, timestamp
from .models import CommunicationLog, DispatchAssignment, EmergencyVehicle, Hospital, Incident, ResponsePlan
from .network import operation_lock
from .response_services import update_response_status


def dispatch_tick(db: Session, current: datetime | None = None) -> None:
    """Advance approved assignments once per stage, recording each arrival exactly once."""
    current = current or now()
    operation_lock(db)
    assignments = list(
        db.scalars(
            select(DispatchAssignment)
            .where(DispatchAssignment.released_at.is_(None), DispatchAssignment.status != "cancelled")
            .with_for_update()
        )
    )
    duration = max(1, settings.dispatch_stage_seconds)
    for assignment in assignments:
        vehicle = db.get(EmergencyVehicle, assignment.vehicle_id)
        incident = db.get(Incident, assignment.incident_id)
        hospital = db.get(Hospital, assignment.hospital_id) if assignment.hospital_id else None
        progress = min(1, max(0, (timestamp(current) - timestamp(assignment.stage_started_at)) / duration))
        assignment.progress = progress
        if assignment.status in {"en_route", "transporting"}:
            origin = (
                (assignment.origin_latitude, assignment.origin_longitude)
                if assignment.status == "en_route"
                else (incident.latitude, incident.longitude)
            )
            destination = (
                (incident.latitude, incident.longitude)
                if assignment.status == "en_route"
                else (hospital.latitude, hospital.longitude)
            )
            # Linear movement is deliberately illustrative; these are not navigable road routes.
            vehicle.latitude = origin[0] + (destination[0] - origin[0]) * progress
            vehicle.longitude = origin[1] + (destination[1] - origin[1]) * progress
        if progress < 1:
            continue
        transitions = {
            "assigned": "en_route",
            "en_route": "on_scene",
            "on_scene": "transporting" if hospital else "completed",
            "transporting": "completed",
        }
        if assignment.status == "completed":
            vehicle.status = "available"
            assignment.released_at = current
            continue
        previous = assignment.status
        assignment.status = transitions[previous]
        vehicle.status = assignment.status
        assignment.stage_started_at, assignment.progress = current, 0
        if assignment.status == "on_scene":
            vehicle.location = incident.location
        if assignment.status == "completed":
            assignment.completed_at = current
            if hospital:
                # Only a real reservation changes capacity; constrained approvals may have unknown counts.
                if assignment.reserved_beds:
                    hospital.reserved_beds -= assignment.reserved_beds
                    hospital.occupied_beds += assignment.reserved_beds
                    assignment.reserved_beds = 0
                vehicle.location = hospital.location
                db.add(
                    CommunicationLog(
                        plan_id=assignment.plan_id,
                        incident_id=incident.id,
                        recipient=hospital.name,
                        recipient_type="hospital",
                        message=f"{vehicle.call_sign} arrived; patients: "
                        f"{assignment.patients if assignment.patients is not None else 'unconfirmed'}."
                        + (" Hospital capacity remains unconfirmed."
                           if hospital.occupied_beds is None else ""),
                        status="acknowledged",
                        acknowledged_at=current,
                    )
                )
    db.flush()
    for plan_id in {a.plan_id for a in assignments}:
        plan = db.get(ResponsePlan, plan_id)
        incident = db.get(Incident, plan.incident_id)
        all_assignments = list(
            db.scalars(select(DispatchAssignment).where(DispatchAssignment.plan_id == plan_id))
        )
        if all(a.released_at for a in all_assignments):
            plan.status, plan.completed_at = "completed", current
            update_response_status(db, incident, "completed")
            db.add(
                CommunicationLog(
                    plan_id=plan.id,
                    incident_id=incident.id,
                    recipient="Kontrol coordination",
                    recipient_type="coordination",
                message="Response completed. All assigned units are available again; arrived patients remain reflected in hospital occupancy.",
                )
            )
        else:
            order = ["assigned", "en_route", "on_scene", "transporting"]
            # Finished support units must not hide a transport still in progress.
            ongoing = [a.status for a in all_assignments if not a.released_at and a.status != "completed"]
            status = max(ongoing, key=order.index) if ongoing else "returning_available"
            update_response_status(db, incident, status)
