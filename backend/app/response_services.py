"""Response-plan orchestration, semantic validation and human approval transactions."""

from collections import Counter
from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import now
from .demo_fleet import vehicle_enabled
from .models import (
    AgentRun,
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
    User,
)
from .network import hospitals, operation_lock, vehicles
from .response_schemas import PlanDecision


def update_response_status(db: Session, incident: Incident, status: str) -> None:
    """Expose only a coarse response status on associated resident-owned reports."""
    incident.response_status = status
    report_ids = select(IncidentReport.report_id).where(IncidentReport.incident_id == incident.id)
    for report in db.scalars(select(Report).where(Report.id.in_(report_ids))):
        report.status = status


def create_plan(
    db: Session, incident: Incident, report: Report, note: str = "Initial response assessment"
) -> ResponsePlan:
    """Start one versioned workflow, without autonomously revising an existing response."""
    db.flush()
    latest = db.scalar(
        select(ResponsePlan)
        .where(ResponsePlan.incident_id == incident.id)
        .order_by(ResponsePlan.revision.desc())
    )
    if latest and latest.status not in {"rejected", "cancelled"}:
        raise HTTPException(409, "An active or completed response already exists for this incident")
    plan = ResponsePlan(
        incident_id=incident.id,
        report_id=report.id,
        revision=latest.revision + 1 if latest else 1,
        revision_note=note,
        simulation=report.simulation,
    )
    db.add(plan)
    db.flush()
    db.add(AgentRun(report_id=report.id, incident_id=incident.id, plan_id=plan.id, stage="intake"))
    incident.response_status = "generating"
    return plan


def validate_assignments(
    requirements: dict, assignments: list[dict], hospital_rows: list[dict], vehicle_rows: list[dict]
) -> None:
    """Reject fabricated IDs, over-allocation, unavailable resources and missing capabilities."""
    expected_patients = requirements.get("estimated_patients")
    hospital_lookup = {h["id"]: h for h in hospital_rows}
    vehicle_lookup = {v["id"]: v for v in vehicle_rows}
    used = set()
    beds = Counter()
    total_patients = 0
    for proposal in assignments:
        vehicle_id = proposal["vehicle_id"]
        if vehicle_id not in vehicle_lookup or vehicle_id in used:
            raise ValueError("Unknown or duplicate vehicle in plan")
        vehicle = vehicle_lookup[vehicle_id]
        if vehicle["status"] != "available" or vehicle["assignment"]:
            raise ValueError(f"Vehicle {vehicle['call_sign']} is no longer available")
        patients = proposal["patients"]
        if patients is None:
            raise ValueError("Patient allocation must be confirmed before approval")
        if patients < 0 or patients > vehicle["patient_capacity"]:
            raise ValueError("Vehicle patient capacity exceeded")
        if patients and "patient_transport" not in vehicle["capabilities"]:
            raise ValueError("Vehicle cannot transport patients")
        hospital_id = proposal["hospital_id"]
        if bool(patients) != bool(hospital_id):
            raise ValueError("Patient transport requires a receiving hospital")
        if hospital_id:
            if hospital_id not in hospital_lookup:
                raise ValueError("Unknown receiving hospital")
            hospital = hospital_lookup[hospital_id]
            if hospital["diversion"]:
                raise ValueError("Receiving hospital is diverted")
            if hospital["available_beds"] is None:
                raise ValueError("Receiving hospital capacity has not been confirmed")
            beds[hospital_id] += patients
            if beds[hospital_id] > hospital["available_beds"]:
                raise ValueError(f"Insufficient available beds at {hospital['name']}")
        used.add(vehicle_id)
        total_patients += patients
    if not assignments:
        raise ValueError("At least one vehicle assignment is required")
    if expected_patients is not None and total_patients != expected_patients:
        raise ValueError("Assignments must cover the reported patient count")


def validate_stage(stage: str, output: dict, payload: dict) -> None:
    """Check references and supplied facts in addition to each agent's strict JSON schema."""
    agent_input = payload["agent_input"]
    if stage == "intake":
        if output["incident_id"] != agent_input["incident_id"]:
            raise ValueError("Intake changed the incident ID")
        if output["reported_injuries"] != agent_input["reported_injuries"]:
            raise ValueError("Intake changed the reported injury count")
        return
    if output["incident_id"] != agent_input["incident_id"]:
        raise ValueError(f"{stage.title()} changed the incident ID")
    if stage == "hospital":
        names = [row["name"] for row in output["hospitals"]]
        if len(names) != len({name.casefold() for name in names}):
            raise ValueError("Hospital agent returned duplicate hospitals")
        if not set(name.casefold() for name in output["recommended_hospitals"]).issubset(
            {name.casefold() for name in names}
        ):
            raise ValueError("Hospital recommendations must reference discovered hospitals")
        return
    if stage == "dispatch":
        available = {row["vehicle_id"] for row in agent_input["available_vehicles"]}
        ids = [row["vehicle_id"] for row in output["recommended_vehicles"]]
        if len(ids) != len(set(ids)) or not set(ids).issubset(available):
            raise ValueError("Dispatch agent referenced an unknown, duplicate, or unavailable vehicle")
        return
    recommended_hospitals = {
        name.casefold()
        for name in agent_input["hospital_result"].get("recommended_hospitals", [])
    }
    recommended_vehicles = {
        row["vehicle_id"]
        for row in agent_input["dispatch_result"].get("recommended_vehicles", [])
    }
    if any(
        row["hospital_name"].casefold() not in recommended_hospitals
        for row in output["hospital_assignments"]
    ):
        raise ValueError("Planner referenced a hospital not recommended by Hospital Finder")
    if any(row["vehicle_id"] not in recommended_vehicles for row in output["vehicle_assignments"]):
        raise ValueError("Planner referenced a vehicle not recommended by Dispatch Finder")
    if output["status"] == "awaiting_approval" and output["unfilled_requirements"]:
        raise ValueError("Plans with unfilled requirements must need information")


def decide_plan(db: Session, plan_id: str, user: User, decision: PlanDecision) -> ResponsePlan:
    """Apply an explicit human decision and reserve resources atomically only on approval."""
    operation_lock(db)
    plan = db.scalar(select(ResponsePlan).where(ResponsePlan.id == plan_id).with_for_update())
    if not plan:
        raise HTTPException(404, "Response plan not found")
    if plan.version != decision.version:
        raise HTTPException(409, "Plan changed. Refresh before deciding.")
    if plan.status not in {"awaiting_approval", "needs_information"}:
        raise HTTPException(409, "Only plans awaiting review can be approved, rejected or revised")
    incident = db.scalar(select(Incident).where(Incident.id == plan.incident_id).with_for_update())
    plan.decision_note = decision.note
    if decision.action in {"reject", "revise"}:
        plan.status = "rejected"
        update_response_status(db, incident, "rejected")
        if decision.action == "revise":
            create_plan(db, incident, db.get(Report, plan.report_id), decision.note)
            update_response_status(db, incident, "generating")
    else:
        if plan.status != "awaiting_approval" or not plan.feasible:
            raise HTTPException(409, "This plan is not feasible; review constraints and request a revision")
        proposals = list(db.scalars(select(ProposedAssignment).where(ProposedAssignment.plan_id == plan.id)))
        # Lock in a fixed order, rechecking current capacity rather than trusting the earlier agent snapshot.
        fleet = {
            v.id: v
            for v in db.scalars(select(EmergencyVehicle).order_by(EmergencyVehicle.id).with_for_update())
        }
        network = {h.id: h for h in db.scalars(select(Hospital).order_by(Hospital.id).with_for_update())}
        try:
            validate_assignments(
                plan.requirements,
                [
                    {"vehicle_id": p.vehicle_id, "hospital_id": p.hospital_id, "patients": p.patients}
                    for p in proposals
                ],
                hospitals(db, incident),
                [v for v in vehicles(db, incident) if vehicle_enabled(v["id"], v["simulation"])],
            )
        except ValueError as exc:
            raise HTTPException(409, f"Resources changed: {exc}. Request a revised plan.") from None
        plan.status, plan.approved_by, plan.approved_at = "approved", user.id, now()
        update_response_status(db, incident, "assigned")
        receiving = Counter()
        for proposal in proposals:
            vehicle = fleet[proposal.vehicle_id]
            vehicle.status = "assigned"
            db.add(
                DispatchAssignment(
                    plan_id=plan.id,
                    incident_id=incident.id,
                    vehicle_id=vehicle.id,
                    hospital_id=proposal.hospital_id,
                    patients=proposal.patients,
                    origin_latitude=vehicle.latitude,
                    origin_longitude=vehicle.longitude,
                )
            )
            destination = network[proposal.hospital_id].name if proposal.hospital_id else "incident support"
            db.add(
                CommunicationLog(
                    plan_id=plan.id,
                    incident_id=incident.id,
                    recipient=vehicle.call_sign,
                    recipient_type="responder",
                message=f"Approved response assignment to {incident.location}; {proposal.patients} patient(s); destination: {destination}.",
                )
            )
            if proposal.hospital_id:
                network[proposal.hospital_id].reserved_beds += proposal.patients
                receiving[proposal.hospital_id] += proposal.patients
        for hospital_id, patients in receiving.items():
            db.add(
                CommunicationLog(
                    plan_id=plan.id,
                    incident_id=incident.id,
                    recipient=network[hospital_id].name,
                    recipient_type="hospital",
                message=f"{patients} patient(s) expected from {incident.location}. Beds reserved for approved plan {plan.id[:8]}.",
                )
            )
        db.add(
            CommunicationLog(
                plan_id=plan.id,
                incident_id=incident.id,
                recipient="Kontrol coordination",
                recipient_type="coordination",
            message=f"Coordinator approved response at {incident.location}. {len(proposals)} unit(s) assigned.",
            )
        )
    db.add(
        CoordinatorAction(
            user_id=user.id,
            incident_id=incident.id,
            action=f"plan_{decision.action}",
            details=f"Plan revision {plan.revision}: {decision.note}",
        )
    )
    db.flush()
    return plan
