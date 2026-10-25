"""Transactional application operations shared by HTTP and simulation ingestion."""

from hashlib import sha256
from uuid import UUID

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import now
from .models import (
    CoordinatorAction,
    Incident,
    IncidentReport,
    PublicUpdate,
    Report,
    Resource,
    ResourceRequest,
    User,
)
from .schemas import IncidentAction, ReportInput


def token_hash(token: str) -> str:
    """Store token digests so database reads do not reveal bearer credentials."""
    return sha256(token.encode()).hexdigest()


def require_record(db: Session, model, record_id: str):
    """Resolve a record or return a consistent HTTP not-found response."""
    try:
        UUID(record_id)
    except (ValueError, TypeError, AttributeError):
        raise HTTPException(404, "Record not found") from None
    record = db.get(model, record_id)
    if not record:
        raise HTTPException(404, "Record not found")
    return record


def ingest_report(
    db: Session, user: User, data: ReportInput, source: str = "resident", incident: Incident | None = None, *, simulation: bool = False
) -> Report:
    """Persist the original report and intake job together before acknowledging it."""
    report = Report(
        user_id=user.id,
        source=source,
        simulation=simulation,
        **data.model_dump(),
    )
    db.add(report)
    if incident is None:
        incident = Incident(
            title=f"{data.category.title()} observation · {data.location}",
            category=data.category,
            reported_casualties=data.reported_casualties,
            latitude=data.latitude,
            longitude=data.longitude,
            location=data.location,
            simulation=simulation,
        )
        db.add(incident)
    db.flush()
    db.add(IncidentReport(incident_id=incident.id, report_id=report.id))
    from .response_services import create_plan
    from .models import ResponsePlan

    # Further reports preserve observations; an existing response is never automatically replanned.
    if not db.scalar(select(ResponsePlan).where(ResponsePlan.incident_id == incident.id)):
        create_plan(db, incident, report)
    db.flush()
    return report


def apply_incident_action(db: Session, incident: Incident, user: User, data: IncidentAction) -> None:
    """Apply a human decision with version protection and append-only provenance."""
    if incident.version != data.version:
        raise HTTPException(409, "Incident changed. Refresh and review the latest version.")
    transitions = {
        "verify": ({"needs_review", "disputed"}, "verified"),
        "dispute": ({"needs_review", "verified"}, "disputed"),
        "resolve": ({"verified"}, "resolved"),
        "reopen": ({"resolved", "disputed"}, "needs_review"),
    }
    if data.action in transitions:
        allowed, target = transitions[data.action]
        if incident.status not in allowed:
            raise HTTPException(409, f"Cannot {data.action} an incident in {incident.status}")
        incident.status = target
    elif data.action == "assign":
        assignee = require_record(db, User, data.target_id or user.id)
        if assignee.role != "coordinator":
            raise HTTPException(422, "Assignee must be a coordinator")
        incident.assigned_to = assignee.id
    elif data.action == "merge":
        target = require_record(db, Incident, data.target_id or "")
        if target.id == incident.id or target.status == "merged" or incident.status == "merged":
            raise HTTPException(409, "Choose another active incident")
        for link in db.scalars(select(IncidentReport).where(IncidentReport.incident_id == incident.id)):
            existing = db.scalar(
                select(IncidentReport).where(
                    IncidentReport.incident_id == target.id, IncidentReport.report_id == link.report_id
                )
            )
            if not existing:
                db.add(IncidentReport(incident_id=target.id, report_id=link.report_id))
        incident.status, incident.merged_into = "merged", target.id
    incident.version += 1
    db.add(CoordinatorAction(user_id=user.id, incident_id=incident.id, action=data.action, details=data.note))


def publish_update(db: Session, update: PublicUpdate, user: User) -> None:
    """Publish a snapshot only after explicit review of a verified incident."""
    incident = require_record(db, Incident, update.incident_id)
    if incident.status not in {"verified", "resolved"}:
        raise HTTPException(409, "Verify the incident before publishing")
    if update.status not in {"draft", "pending"}:
        raise HTTPException(409, "Only draft or pending updates can be published")
    update.status, update.approved_by, update.published_at = "published", user.id, now()
    db.add(
        CoordinatorAction(
            user_id=user.id,
            incident_id=incident.id,
            action="publish",
            details=f"Published SIMULATION update: {update.title}",
        )
    )


def approve_resource(db: Session, request: ResourceRequest, user: User) -> None:
    """Reserve capacity under a lock so concurrent approvals cannot over-allocate."""
    resource = db.scalar(select(Resource).where(Resource.id == request.resource_id).with_for_update())
    if request.status != "pending":
        raise HTTPException(409, "Request already decided")
    if resource.occupancy + request.quantity > resource.capacity:
        raise HTTPException(409, "Insufficient available capacity")
    resource.occupancy += request.quantity
    resource.confirmed_at = now()
    request.status, request.approved_by = "approved", user.id
    db.add(
        CoordinatorAction(
            user_id=user.id,
            incident_id=request.incident_id,
            action="resource_assignment",
            details=f"SIMULATION: {request.quantity} units at {resource.name}",
        )
    )
