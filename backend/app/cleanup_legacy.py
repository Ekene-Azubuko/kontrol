"""Explicit, transactional cleanup of the retired exercise dataset."""

import json
from sqlalchemy import delete, or_, select, update
from sqlalchemy.orm import Session
from .db import SessionLocal
from .models import (
    AgentFinding, AgentRun, Call, CommunicationLog, CoordinatorAction,
    DispatchAssignment, EmergencyVehicle, Evidence, Hospital, HospitalInventory,
    Incident, IncidentReport, ProposedAssignment, PublicUpdate, Report,
    Resource, ResourceRequest, ResponsePlan, Simulation, Subscription,
)
from .network import operation_lock


def cleanup_legacy(db: Session) -> dict[str, int]:
    """Remove retired test history, preserving calls and workflows that do not depend on the legacy fleet."""
    operation_lock(db)
    kept_reports = set(db.scalars(select(Call.report_id).where(
        Call.sample_key.is_(None), Call.report_id.is_not(None),
    )))
    legacy_vehicle_ids = set(db.scalars(select(EmergencyVehicle.id).where(EmergencyVehicle.call_sign.like("SIM-%"))))
    legacy_plan_ids = set(db.scalars(select(ProposedAssignment.plan_id).where(ProposedAssignment.vehicle_id.in_(legacy_vehicle_ids))))
    legacy_plan_ids.update(db.scalars(select(DispatchAssignment.plan_id).where(DispatchAssignment.vehicle_id.in_(legacy_vehicle_ids))))
    # A saved call may have an old auto-completed response using the retired fleet.
    # Preserve its source recording, but return it to review instead of retaining fictional execution history.
    legacy_reports = set(db.scalars(select(ResponsePlan.report_id).where(ResponsePlan.id.in_(legacy_plan_ids))))
    kept_reports -= legacy_reports
    removed_reports = set(db.scalars(select(Report.id).where(Report.id.not_in(kept_reports))))
    kept_incidents = set(db.scalars(select(IncidentReport.incident_id).where(
        IncidentReport.report_id.in_(kept_reports),
    )))
    kept_incidents.update(db.scalars(select(ResponsePlan.incident_id).where(ResponsePlan.report_id.in_(kept_reports))))
    kept_incidents.update(db.scalars(select(AgentRun.incident_id).where(AgentRun.report_id.in_(kept_reports))))
    removed_incidents = set(db.scalars(select(Incident.id).where(Incident.id.not_in(kept_incidents))))
    removed_plans = set(db.scalars(select(ResponsePlan.id).where(ResponsePlan.report_id.in_(removed_reports))))
    removed_runs = set(db.scalars(select(AgentRun.id).where(AgentRun.report_id.in_(removed_reports))))
    counts = {}

    def remove(model, *conditions):
        """Delete dependent records first and return concrete counts for the cleanup report."""
        result = db.execute(delete(model).where(*conditions).execution_options(synchronize_session=False))
        counts[model.__tablename__] = result.rowcount

    # Communications, inventory and community publishing belong entirely to the retired product flow.
    for model in [CommunicationLog, HospitalInventory, ResourceRequest, Resource, PublicUpdate, Subscription]:
        remove(model)
    remove(AgentFinding, or_(AgentFinding.run_id.in_(removed_runs), AgentFinding.incident_id.in_(removed_incidents)))
    remove(Evidence, or_(Evidence.report_id.in_(removed_reports), Evidence.incident_id.in_(removed_incidents)))
    remove(ProposedAssignment, ProposedAssignment.plan_id.in_(removed_plans))
    remove(DispatchAssignment, DispatchAssignment.plan_id.in_(removed_plans))
    remove(AgentRun, AgentRun.id.in_(removed_runs))
    remove(ResponsePlan, ResponsePlan.id.in_(removed_plans))
    remove(CoordinatorAction, or_(
        CoordinatorAction.incident_id.in_(removed_incidents),
        CoordinatorAction.action.in_(["message_acknowledged", "resource_edit", "response_demo_reset"]),
    ))
    remove(IncidentReport, or_(IncidentReport.report_id.in_(removed_reports), IncidentReport.incident_id.in_(removed_incidents)))
    # Keep source recordings/transcripts so the fallback can be started afresh; never retain dangling report links.
    for call in db.scalars(select(Call).where(Call.report_id.in_(removed_reports))):
        call.report_id = None
        call.status = "awaiting_review" if call.original_transcript else "failed"
        call.confirmed_by = call.confirmed_at = None
    db.flush()
    remove(Report, Report.id.in_(removed_reports))
    db.execute(update(Incident).where(Incident.merged_into.in_(removed_incidents)).values(merged_into=None))
    remove(Incident, Incident.id.in_(removed_incidents))
    used_vehicles = set(db.scalars(select(ProposedAssignment.vehicle_id))) | set(db.scalars(select(DispatchAssignment.vehicle_id)))
    used_hospitals = set(db.scalars(select(ProposedAssignment.hospital_id))) | set(db.scalars(select(DispatchAssignment.hospital_id)))
    # Never break a retained real-call assignment if a legacy resource was explicitly used in it.
    remove(EmergencyVehicle, EmergencyVehicle.call_sign.like("SIM-%"), EmergencyVehicle.id.not_in(used_vehicles))
    remove(Hospital, Hospital.simulation.is_(True), Hospital.id.not_in(used_hospitals - {None}))
    db.execute(update(Hospital).values(total_beds=None, occupied_beds=None, baseline_occupied=None, reserved_beds=0, diversion=None))
    db.execute(update(DispatchAssignment).values(reserved_beds=0))
    active_vehicle_ids = set(db.scalars(select(DispatchAssignment.vehicle_id).where(DispatchAssignment.released_at.is_(None))))
    for vehicle in db.scalars(select(EmergencyVehicle).where(EmergencyVehicle.id.not_in(active_vehicle_ids))):
        vehicle.status = "available"
        vehicle.latitude, vehicle.longitude, vehicle.location = vehicle.home_latitude, vehicle.home_longitude, vehicle.home_location
    for state in db.scalars(select(Simulation)):
        state.running, state.cursor = False, 0
    db.flush()
    return counts


if __name__ == "__main__":
    with SessionLocal() as session:
        counts = cleanup_legacy(session)
        session.commit()
        print(json.dumps(counts, indent=2))
