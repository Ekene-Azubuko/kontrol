"""Repeatable fictional San Francisco earthquake-response exercise data."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from .db import now
from .models import (
    AgentRun,
    Call,
    CoordinatorAction,
    DispatchAssignment,
    EmergencyVehicle,
    Hospital,
    HospitalInventory,
    Incident,
    Report,
    ResponsePlan,
    Simulation,
    User,
)
from .network import operation_lock
from .response_services import update_response_status
from .schemas import ReportInput
from .services import ingest_report

HOSPITALS = [
    (
        "SIM · Bayview Response Hospital",
        "Bayview exercise site",
        37.735,
        -122.395,
        ["emergency", "trauma"],
        40,
        24,
        False,
    ),
    (
        "SIM · Mission Care Center",
        "Mission exercise site",
        37.756,
        -122.42,
        ["emergency", "trauma", "burns"],
        36,
        25,
        False,
    ),
    (
        "SIM · Sunset Community Hospital",
        "Sunset exercise site",
        37.754,
        -122.485,
        ["emergency", "pediatric"],
        30,
        22,
        False,
    ),
    (
        "SIM · Pacific Heights Medical",
        "Pacific Heights exercise site",
        37.788,
        -122.439,
        ["emergency", "trauma", "pediatric"],
        32,
        28,
        False,
    ),
    (
        "SIM · Harbor Emergency Center",
        "Harbor exercise site",
        37.798,
        -122.405,
        ["emergency", "burns"],
        24,
        24,
        True,
    ),
    (
        "SIM · Richmond Response Hospital",
        "Richmond exercise site",
        37.779,
        -122.472,
        ["emergency", "trauma", "burns"],
        42,
        29,
        False,
    ),
]


def seed_network(db: Session) -> bool:
    """Add the new network to existing installations without replacing historical records."""
    if db.scalar(select(Hospital)):
        return False
    for index, (name, location, latitude, longitude, capabilities, total, occupied, diversion) in enumerate(
        HOSPITALS
    ):
        hospital = Hospital(
            name=name,
            location=location,
            latitude=latitude,
            longitude=longitude,
            capabilities=capabilities,
            total_beds=total,
            occupied_beds=occupied,
            baseline_occupied=occupied,
            diversion=diversion,
        )
        db.add(hospital)
        db.flush()
        for item, category, quantity, threshold in [
            ("Exercise medicine kits", "medicine", 18 + index, 10),
            ("Oxygen units", "equipment", 3 if index == 1 else 14, 5),
            ("Trauma equipment kits", "equipment", 8 + index, 5),
        ]:
            db.add(
                HospitalInventory(
                    hospital_id=hospital.id,
                    name=item,
                    category=category,
                    quantity=quantity,
                    low_stock_threshold=threshold,
                )
            )
    for index in range(10):
        kind = "ambulance" if index < 6 else "fire_engine" if index < 8 else "rescue_unit"
        capabilities = (
            ["patient_transport", "advanced_life_support"]
            if index < 5
            else ["patient_transport"]
            if index == 5
            else ["fire_suppression", "rescue"]
            if index < 8
            else ["rescue"]
        )
        latitude = 37.746 + (index // 4) * 0.022
        longitude = -122.472 + (index % 4) * 0.025
        location = ["Sunset staging", "Mission staging", "SoMa staging", "Bay staging"][index % 4]
        db.add(
            EmergencyVehicle(
                call_sign=f"SIM-{['AMB', 'ENG', 'RES'][0 if index < 6 else 1 if index < 8 else 2]}-{index + 1:02d}",
                vehicle_type=kind,
                capabilities=capabilities,
                patient_capacity=2 if index < 6 else 0,
                latitude=latitude,
                longitude=longitude,
                home_latitude=latitude,
                home_longitude=longitude,
                location=location,
                home_location=location,
            )
        )
    if not db.scalar(select(Simulation)):
        db.add(Simulation())
    db.flush()
    return True


def response_report(index: int = 0) -> ReportInput:
    """Return one of three fixed observations from the same fictional earthquake exercise."""
    cases = [
        (
            "collision",
            "Market & 8th exercise area",
            37.777,
            -122.414,
            2,
            "SIMULATION: Earthquake exercise. Two vehicles collided; two people are reported injured. No medical diagnoses supplied.",
        ),
        (
            "fire",
            "Mission exercise block",
            37.758,
            -122.421,
            1,
            "SIMULATION: Earthquake exercise. Small building fire with one reported injured person.",
        ),
        (
            "rescue",
            "Richmond exercise block",
            37.78,
            -122.46,
            0,
            "SIMULATION: Earthquake exercise. Fallen debris blocks access; no injuries reported.",
        ),
    ]
    category, location, latitude, longitude, casualties, description = cases[index % len(cases)]
    return ReportInput(
        category=category,
        location=location,
        latitude=latitude,
        longitude=longitude,
        reported_casualties=casualties,
        description=description,
        observed_at=now(),
    )


def start_demo(db: Session, resident: User, index: int = 0) -> Report:
    """Feed a prepared observation through the same durable ingestion path as resident reports."""
    return ingest_report(db, resident, response_report(index), source="response_demo", simulation=True)


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
    for call in db.scalars(select(Call).where(Call.simulation.is_(True), Call.status != "confirmed")):
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
    for hospital in db.scalars(select(Hospital).where(Hospital.simulation.is_(True))):
        hospital.occupied_beds, hospital.reserved_beds = hospital.baseline_occupied, 0
    db.add(
        CoordinatorAction(
            user_id=user.id,
            action="response_demo_reset",
            details="SIMULATION: Cancelled exercise responses and restored fleet/bed baselines. Reports, plans and communication history retained.",
        )
    )
