"""Opt-in, database-backed hackathon fleet, independent of simulated incidents and hospitals."""

from uuid import NAMESPACE_URL, uuid5
from sqlalchemy.orm import Session
from .config import settings
from .models import EmergencyVehicle


FLEET = [
    ("AMB-01", "ambulance", 37.7763, -122.4101, "SoMa", ["patient_transport", "advanced_life_support"], 2),
    ("AMB-02", "ambulance", 37.7650, -122.4210, "Mission", ["patient_transport", "advanced_life_support"], 2),
    ("POL-01", "police", 37.7830, -122.4120, "Civic Center", ["traffic_control", "scene_security"], 0),
    ("POL-02", "police", 37.7700, -122.4290, "Hayes Valley", ["traffic_control", "scene_security"], 0),
    ("FIR-01", "fire_engine", 37.7750, -122.4180, "Civic Center", ["fire_suppression", "rescue"], 0),
    ("RES-01", "rescue_unit", 37.7810, -122.4030, "SoMa", ["rescue", "extrication"], 0),
]
FLEET_IDS = {name: str(uuid5(NAMESPACE_URL, f"kontrol:demo-fleet:{name}")) for name, *_ in FLEET}


def vehicle_enabled(vehicle_id: str, simulation: bool) -> bool:
    """Allow only this explicitly opted-in demo fleet alongside real vehicles in live mode."""
    return (
        settings.creao_mode == "mock"
        or not simulation
        or (settings.demo_fleet_enabled and vehicle_id in FLEET_IDS.values())
    )


def seed_demo_fleet(db: Session) -> None:
    """Insert missing demo units without resetting assigned units or their current positions."""
    if not settings.demo_fleet_enabled and settings.creao_mode != "mock":
        return
    for name, kind, latitude, longitude, location, capabilities, capacity in FLEET:
        if db.get(EmergencyVehicle, FLEET_IDS[name]):
            continue
        db.add(EmergencyVehicle(
            id=FLEET_IDS[name], call_sign=name, vehicle_type=kind,
            latitude=latitude, longitude=longitude, home_latitude=latitude, home_longitude=longitude,
            location=location, home_location=location, capabilities=capabilities,
            patient_capacity=capacity, simulation=True,
        ))
    db.flush()
