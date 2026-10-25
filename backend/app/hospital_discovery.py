"""Persist validated public hospital facts while leaving operational capacity under operator control."""

from sqlalchemy import select
from sqlalchemy.orm import Session
from .models import Hospital


def store_discovered_hospitals(db: Session, hospitals: list[dict], *, refresh_existing: bool = True) -> None:
    """Store destinations from validated Hospital output without adopting agent-reported bed availability."""
    for hospital in hospitals:
        existing = db.scalar(select(Hospital).where(
            Hospital.name.ilike(hospital["name"]), Hospital.location.ilike(hospital["address"]),
        ))
        if existing:
            # Planning retries repair missing rows but must not overwrite newer public facility findings.
            if refresh_existing:
                existing.latitude = hospital["latitude"]
                existing.longitude = hospital["longitude"]
                existing.capabilities = hospital["documented_capabilities"]
                existing.source_urls = hospital["source_urls"]
            continue
        db.add(Hospital(
            name=hospital["name"], location=hospital["address"],
            latitude=hospital["latitude"], longitude=hospital["longitude"],
            capabilities=hospital["documented_capabilities"],
            total_beds=None, occupied_beds=None, baseline_occupied=None,
            diversion=None, simulation=False, source_urls=hospital["source_urls"],
            discovered_by_agent=True,
        ))
    # The planner immediately resolves destination IDs in this same transaction.
    db.flush()
