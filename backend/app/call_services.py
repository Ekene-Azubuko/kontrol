"""Transactional recorded-call review and explicit exercise execution policy."""

import json
from datetime import UTC
from typing import Self

from fastapi import HTTPException
from pydantic import Field, field_validator, model_validator
from sqlalchemy import select
from sqlalchemy.orm import Session

from .config import settings
from .call_location import (
    AUTOMATIC_LOCATION_LIMITATION,
    EDITED_LOCATION_LIMITATION,
    DetectedLocation,
    detect_location,
)
from .db import now
from .models import Call, CoordinatorAction, IncidentReport, ResponsePlan, User
from .network import operation_lock, record
from .schemas import Category, ReportInput, StrictModel
from .services import ingest_report


class CallerLocation(StrictModel):
    """Allow absent caller location while rejecting partial or invalid coordinates."""

    caller_latitude: float | None = Field(default=None, ge=-90, le=90)
    caller_longitude: float | None = Field(default=None, ge=-180, le=180)
    caller_accuracy_m: float | None = Field(default=None, ge=0, le=100000)

    @model_validator(mode="after")
    def paired_coordinates(self) -> Self:
        """A caller pin requires both axes, and accuracy requires a pin."""
        if (self.caller_latitude is None) != (self.caller_longitude is None):
            raise ValueError("Provide both caller coordinates or neither")
        if self.caller_accuracy_m is not None and self.caller_latitude is None:
            raise ValueError("Caller accuracy requires coordinates")
        return self


class ConfirmReview(StrictModel):
    """Require the reviewed text, dispatcher category and explicit incident coordinates."""

    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    address: str = Field(min_length=2, max_length=160)
    transcript: str = Field(min_length=10, max_length=4000)
    category: Category
    version: int = Field(ge=1)


class StartCall(StrictModel):
    """Require only call type and the version shown to the dispatcher."""

    category: Category
    version: int = Field(ge=1)


class LocateCall(StrictModel):
    """Accept optional corrected location text, or retry the call's last location input."""

    address: str | None = Field(default=None, min_length=2, max_length=160)
    version: int = Field(ge=1)

    @field_validator("address", mode="before")
    @classmethod
    def trim_address(cls, value: object) -> object:
        """Reject whitespace-only corrections while preserving the original transcript separately."""
        return value.strip() if isinstance(value, str) else value


def editable_call(db: Session, call_id: str, version: int) -> Call:
    """Lock and refresh a ready call so edits, reset and agent start cannot overwrite one another."""
    operation_lock(db)
    call = db.scalar(
        select(Call).where(Call.id == call_id).with_for_update().execution_options(populate_existing=True)
    )
    if not call:
        raise HTTPException(404, "Call not found")
    if call.status != "awaiting_review" or call.version != version or call.report_id:
        raise HTTPException(409, "Call changed or was already started. Refresh before editing its location.")
    return call


def locate_call(db: Session, call_id: str, user: User, data: LocateCall) -> Call:
    """Resolve location outside database locks, then save only if the observed call version still matches."""
    call = editable_call(db, call_id, data.version)
    if not call.original_transcript:
        raise HTTPException(409, "Wait for transcription before finding the location.")
    previous = call.detected_location
    address = data.address if data.address is not None else (previous or {}).get("input_address")
    transcript = call.original_transcript
    db.commit()  # No database transaction or reset lock may span an external geocoding request.
    location = detect_location(f"At {address}" if address else transcript)
    location.input_source = "dispatcher_address" if address else "transcript"
    location.input_address = address
    location = DetectedLocation.model_validate(location.model_dump())
    call = editable_call(db, call_id, data.version)
    # An unresolved correction replaces the old pin so agents cannot start at an obsolete address.
    call.detected_location = location.model_dump()
    # A retry may return identical JSON; force a new version so concurrent retries still conflict.
    from sqlalchemy.orm.attributes import flag_modified

    flag_modified(call, "detected_location")
    db.add(
        CoordinatorAction(
            user_id=user.id,
            action="call_location_lookup",
            details=json.dumps(
                {
                    "call_id": call.id,
                    "address": address,
                    "previous_location": previous,
                    "location": call.detected_location,
                    "transcript_changed": False,
                }
            ),
        )
    )
    db.flush()
    return call


def start_call(db: Session, call_id: str, user: User, data: StartCall) -> Call:
    """Start from server-owned transcript inference without treating it as human location verification."""
    call = editable_call(db, call_id, data.version)
    location = DetectedLocation.model_validate(call.detected_location) if call.detected_location else None
    if not location or location.status != "resolved" or not call.original_transcript:
        raise HTTPException(
            409,
            "No incident location is available. Edit the address or find the location again before starting agents.",
        )
    result = confirm_review(
        db,
        call_id,
        user,
        ConfirmReview(
            latitude=location.latitude,
            longitude=location.longitude,
            address=location.address,
            transcript=call.original_transcript,
            category=data.category,
            version=data.version,
        ),
        automatic_location=True,
    )
    plan = db.scalar(
        select(ResponsePlan)
        .where(ResponsePlan.report_id == result.report_id)
        .order_by(ResponsePlan.revision.desc())
    )
    plan.constraints = [
        EDITED_LOCATION_LIMITATION
        if location.input_source == "dispatcher_address"
        else AUTOMATIC_LOCATION_LIMITATION
    ]
    db.flush()
    return result


def require_exercise_execution() -> None:
    """Reject disabled paid simulation before creating work that cannot execute."""
    if settings.creao_mode == "live" and not settings.live_simulation_enabled:
        raise HTTPException(
            409, "Enable LIVE_SIMULATION_ENABLED before running fictional calls with live agents."
        )
    if not settings.demo_auth or settings.app_env == "production":
        raise HTTPException(403, "Recorded-call exercises require trusted local demo mode.")


def call_record(db: Session, call: Call) -> dict:
    """Serialize review state without disclosing paths or worker claim credentials."""
    from .call_reopen import REOPENABLE_PLAN_STATUSES

    result = record(call, {"audio_key", "claim_token", "lease_expires_at"})
    result["incident_id"] = None
    result["plan_id"] = None
    result["can_reopen"] = False
    if call.report_id:
        result["incident_id"] = db.scalar(
            select(IncidentReport.incident_id).where(IncidentReport.report_id == call.report_id)
        )
        plan = db.scalar(
            select(ResponsePlan)
            .where(ResponsePlan.report_id == call.report_id)
            .order_by(ResponsePlan.revision.desc())
        )
        if plan:
            result["plan_id"] = plan.id
            result["can_reopen"] = (
                call.status == "confirmed" and plan.status in REOPENABLE_PLAN_STATUSES and not plan.approved_at
            )
    return result


def confirm_review(
    db: Session, call_id: str, user: User, data: ConfirmReview, *, automatic_location: bool = False
) -> Call:
    """Link a single call to a report and plan under the same reset and row locks."""
    require_exercise_execution()
    operation_lock(db)
    call = db.scalar(select(Call).where(Call.id == call_id).with_for_update())
    if not call:
        raise HTTPException(404, "Call not found")
    if call.status != "awaiting_review" or call.version != data.version:
        raise HTTPException(409, "Call changed or was already confirmed. Refresh before reviewing.")
    report = ingest_report(
        db,
        user,
        ReportInput(
            category=data.category,
            description=data.transcript,
            latitude=data.latitude,
            longitude=data.longitude,
            location=data.address,
            observed_at=call.received_at.replace(tzinfo=UTC)
            if call.received_at.tzinfo is None
            else call.received_at,
        ),
        source="911_call",
        simulation=call.simulation,
    )
    call.reviewed_transcript = data.transcript
    call.confirmed_latitude, call.confirmed_longitude = data.latitude, data.longitude
    call.confirmed_address, call.confirmed_by, call.confirmed_at = data.address, user.id, now()
    call.status, call.report_id = "confirmed", report.id
    db.add(
        CoordinatorAction(
            user_id=user.id,
            action="call_confirm_review",
            incident_id=db.scalar(
                select(IncidentReport.incident_id).where(IncidentReport.report_id == report.id)
            ),
            details=json.dumps(
                {
                    "call_id": call.id,
                    "transcript_changed": data.transcript != call.original_transcript,
                    "caller_location": [call.caller_latitude, call.caller_longitude],
                    "confirmed_location": [data.latitude, data.longitude],
                    "address": data.address,
                    "category": data.category,
                    "location_confirmation": (
                        "automatic_from_dispatcher_address"
                        if (call.detected_location or {}).get("input_source") == "dispatcher_address"
                        else "automatic_from_transcript"
                    )
                    if automatic_location
                    else "dispatcher_reviewed",
                    "location_source": (call.detected_location or {}).get("source")
                    if automatic_location
                    else "dispatcher",
                }
            ),
        )
    )
    db.flush()
    return call
