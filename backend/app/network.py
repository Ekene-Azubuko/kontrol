"""Backend-owned simulated capacity, fleet and illustrative travel estimates."""

from math import asin, cos, radians, sin, sqrt
from sqlalchemy import inspect, select
from sqlalchemy.orm import Session
from .models import DispatchAssignment, EmergencyVehicle, Hospital, HospitalInventory, Incident, Simulation


def record(row, exclude: set[str] | None = None) -> dict:
    """Serialize mapped columns without traversing private relationships."""
    return {
        column.key: getattr(row, column.key)
        for column in inspect(row).mapper.column_attrs
        if column.key not in (exclude or set())
    }


def operation_lock(db: Session) -> None:
    """Serialize short network mutations against reset; never hold this during agent calls."""
    db.scalar(select(Simulation).with_for_update())


def travel_minutes(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Estimate illustrative travel at 30 km/h with a 1.35 distance factor and two-minute overhead."""
    a = (
        sin(radians(lat2 - lat1) / 2) ** 2
        + cos(radians(lat1)) * cos(radians(lat2)) * sin(radians(lon2 - lon1) / 2) ** 2
    )
    distance = 6371 * 2 * asin(min(1, sqrt(a)))
    return round(2 + distance * 1.35 / 30 * 60, 1)


def hospitals(db: Session, incident: Incident | None = None) -> list[dict]:
    """Supply real database capacity snapshots, including reservations and simple inventory."""
    result = []
    for row in db.scalars(select(Hospital).order_by(Hospital.name)):
        result.append(
            {
                **record(row),
                "available_beds": (
                    row.total_beds - (row.occupied_beds or 0) - row.reserved_beds
                    if row.total_beds is not None
                    else None
                ),
                "travel_minutes": travel_minutes(
                    incident.latitude, incident.longitude, row.latitude, row.longitude
                )
                if incident
                else None,
                "inventory": [
                    record(item)
                    for item in db.scalars(
                        select(HospitalInventory).where(HospitalInventory.hospital_id == row.id)
                    )
                ],
            }
        )
    return result


def vehicles(db: Session, incident: Incident | None = None) -> list[dict]:
    """Expose current fleet locations and active assignments to operational agents and coordinators."""
    result = []
    for row in db.scalars(select(EmergencyVehicle).order_by(EmergencyVehicle.call_sign)):
        assignment = db.scalar(
            select(DispatchAssignment).where(
                DispatchAssignment.vehicle_id == row.id,
                DispatchAssignment.released_at.is_(None),
                DispatchAssignment.status != "cancelled",
            )
        )
        result.append(
            {
                **record(row),
                "travel_minutes": travel_minutes(
                    row.latitude, row.longitude, incident.latitude, incident.longitude
                )
                if incident
                else None,
                "assignment": record(assignment) if assignment else None,
            }
        )
    return result
