"""Idempotent simulation seed and optional paced replay through normal report ingestion."""

from sqlalchemy import select
from .config import settings
from .demo_fleet import seed_demo_fleet
from .db import SessionLocal, now, timestamp
from .models import Simulation, User
from .services import token_hash


def seed(db) -> None:
    """Initialize the dispatcher, queue lock and optional fleet without creating incidents or hospitals."""
    if not db.scalar(select(User).where(User.role == "coordinator")):
        db.add(User(name="Jordan Lee · Demo dispatcher", role="coordinator", token_hash=token_hash("demo-coordinator")))
        db.flush()
    if not db.scalar(select(Simulation)):
        db.add(Simulation())
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
    from .call_api import sample_call
    from .sample_calls import SAMPLES

    user = db.scalar(select(User).where(User.role == "coordinator"))
    key = list(SAMPLES)[state.cursor]
    # Advance the replay cursor in the same transaction as insertion to avoid duplicate calls.
    state.cursor += 1
    state.last_event_at = now()
    sample_call(key, db, user)


if __name__ == "__main__":
    with SessionLocal() as session:
        if settings.demo_auth and settings.app_env != "production":
            seed(session)
