"""Idempotent simulation seed and optional paced replay through normal report ingestion."""

from sqlalchemy import select
from .config import settings
from .demo_fleet import seed_demo_fleet
from .db import SessionLocal, now, timestamp
from .models import Resource, Simulation, User
from .response_seed import response_report, seed_network, start_demo
from .services import ingest_report, token_hash


def seed(db) -> None:
    """Seed one earthquake exercise; existing reports, users and public records are preserved."""
    existing = db.scalar(select(User))
    if not existing:
        db.add_all(
            [
                User(
                    name="Alex Morgan · Demo resident",
                    role="resident",
                    token_hash=token_hash("demo-resident"),
                ),
                User(
                    name="Jordan Lee · Demo coordinator",
                    role="coordinator",
                    token_hash=token_hash("demo-coordinator"),
                ),
            ]
        )
        db.flush()
    created_network = seed_network(db)
    if created_network:
        resident = db.scalar(select(User).where(User.role == "resident"))
        for index in range(3):
            start_demo(db, resident, index)
    if not existing:
        # Retain the useful public help directory without exposing operational hospital or fleet records.
        for index, name in enumerate(
            [
                "Sunset shelter",
                "Mission community hall",
                "Richmond water station",
                "Bayview aid point",
                "SoMa food hub",
                "Harbor transport hub",
            ]
        ):
            db.add(
                Resource(
                    name=f"SIM · {name}",
                    category=["shelter", "shelter", "water", "medical", "food", "transportation"][index],
                    location=f"{name.split()[0]} exercise area",
                    latitude=37.75 + (index // 3) * 0.025,
                    longitude=-122.48 + (index % 3) * 0.03,
                    capacity=100,
                    occupancy=30 + index * 5,
                    accessible=True,
                    pet_friendly=index % 2 == 0,
                )
            )
    seed_demo_fleet(db)
    db.commit()


def simulation_tick(db, state: Simulation) -> None:
    """Replay three prepared observations at a bounded rate without automatically revising plans."""
    if not state.running or state.cursor >= 3:
        state.running = False
        return
    if settings.creao_mode == "live" and not settings.live_simulation_enabled:
        state.running = False
        return
    if now().timestamp() - timestamp(state.last_event_at) < max(2, 15 / state.speed):
        return
    resident = db.scalar(select(User).where(User.role == "resident"))
    ingest_report(db, resident, response_report(state.cursor), source="simulation_replay")
    state.cursor += 1
    state.last_event_at = now()


if __name__ == "__main__":
    with SessionLocal() as session:
        if settings.demo_auth and settings.app_env != "production":
            seed(session)
