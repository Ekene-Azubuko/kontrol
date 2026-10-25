"""Dispatcher-only simulated recording upload, playback and review endpoints."""

from typing import Annotated

from fastapi import APIRouter, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from pydantic import ValidationError
from sqlalchemy import select

from .call_audio import audio_path, save_upload
from .call_reopen import ReopenCall, reopen_call
from .call_services import (
    CallerLocation,
    ConfirmReview,
    call_record,
    confirm_review,
    require_exercise_execution,
    StartCall,
    start_call,
    LocateCall,
    locate_call,
)
from .dependencies import Coordinator, DB
from .models import Call, CoordinatorAction
from .network import operation_lock
from .sample_calls import SAMPLES
from .services import require_record

router = APIRouter(prefix="/calls", tags=["Recorded-call exercises"])


def persist_recording(
    db: DB, upload: UploadFile, location: CallerLocation, sample_key: str | None = None
) -> dict:
    """Keep validated audio only when its database record is durable."""
    require_exercise_execution()
    key, content_type, duration = save_upload(upload)
    try:
        operation_lock(db)
        call = Call(
            audio_key=key,
            audio_content_type=content_type,
            duration_seconds=duration,
            sample_key=sample_key,
            simulation=True,
            **location.model_dump(),
        )
        db.add(call)
        db.flush()
        result = call_record(db, call)
        db.commit()
        return result
    except Exception:
        db.rollback()
        audio_path(key).unlink(missing_ok=True)
        raise


@router.post("", status_code=201)
def upload_call(
    db: DB,
    user: Coordinator,
    audio: Annotated[UploadFile, File()],
    caller_latitude: Annotated[float | None, Form()] = None,
    caller_longitude: Annotated[float | None, Form()] = None,
    caller_accuracy_m: Annotated[float | None, Form()] = None,
):
    """Accept fictional audio with optional approximate caller coordinates."""
    try:
        location = CallerLocation(
            caller_latitude=caller_latitude,
            caller_longitude=caller_longitude,
            caller_accuracy_m=caller_accuracy_m,
        )
    except ValidationError:
        raise HTTPException(
            422, "Provide valid paired caller coordinates and accuracy, or omit them."
        ) from None
    return persist_recording(db, audio, location)


@router.get("/samples")
def samples(user: Coordinator):
    """List only available fictional fixtures, never internal filenames."""
    return [{"key": sample.key, "title": sample.title, "simulation": True} for sample in SAMPLES.values()]


@router.post("/sample/{key}", status_code=201)
def sample_call(key: str, db: DB, user: Coordinator):
    """Queue bundled audio through the ordinary transcription workflow."""
    sample = SAMPLES.get(key)
    if sample is None:
        raise HTTPException(404, "Sample not found")
    from starlette.datastructures import Headers

    with sample.audio_path.open("rb") as recording:
        upload = UploadFile(recording, filename=f"{key}.wav", headers=Headers({"content-type": "audio/wav"}))
        return persist_recording(
            db,
            upload,
            CallerLocation(
                caller_latitude=sample.latitude, caller_longitude=sample.longitude, caller_accuracy_m=180
            ),
            key,
        )


@router.get("")
def calls(db: DB, user: Coordinator):
    """Return a bounded private queue in newest-first order."""
    return [
        call_record(db, call)
        for call in db.scalars(select(Call).order_by(Call.received_at.desc()).limit(100))
    ]


@router.get("/{call_id}")
def call_detail(call_id: str, db: DB, user: Coordinator):
    """Return original and reviewed text only to dispatchers."""
    return call_record(db, require_record(db, Call, call_id))


@router.get("/{call_id}/audio")
def call_audio(call_id: str, db: DB, user: Coordinator):
    """Serve authenticated audio without exposing private storage paths."""
    call = require_record(db, Call, call_id)
    path = audio_path(call.audio_key)
    if not path.is_file():
        raise HTTPException(404, "Recording not found")
    return FileResponse(path, media_type=call.audio_content_type, headers={"Cache-Control": "no-store"})


@router.post("/{call_id}/confirm-review")
def review(call_id: str, data: ConfirmReview, db: DB, user: Coordinator):
    """Confirm text and incident location, then acknowledge the durable agent workflow."""
    call = confirm_review(db, call_id, user, data)
    db.commit()
    return call_record(db, call)


@router.post("/{call_id}/start")
def start(call_id: str, data: StartCall, db: DB, user: Coordinator):
    """Start agents with a selected call type and automatically inferred incident location."""
    call = start_call(db, call_id, user, data)
    db.commit()
    return call_record(db, call)


@router.post("/{call_id}/locate")
def locate(call_id: str, data: LocateCall, db: DB, user: Coordinator):
    """Retry geocoding or correct location text without retranscribing or starting agents."""
    call = locate_call(db, call_id, user, data)
    db.commit()
    return call_record(db, call)


@router.post("/{call_id}/reopen")
def reopen(call_id: str, data: ReopenCall, db: DB, user: Coordinator):
    """Return an unapproved call to type selection without retranscribing or invoking agents."""
    call = reopen_call(db, call_id, user, data)
    db.commit()
    return call_record(db, call)


@router.post("/{call_id}/retry-transcription")
def retry(call_id: str, db: DB, user: Coordinator):
    """Requeue failed work with a fresh claim and an explicit audit event."""
    require_exercise_execution()
    operation_lock(db)
    call = db.scalar(select(Call).where(Call.id == call_id).with_for_update())
    if not call:
        raise HTTPException(404, "Call not found")
    if call.status != "failed" or call.attempts >= 3 or call.report_id:
        raise HTTPException(409, "Only failed calls with fewer than three attempts can retry.")
    call.status, call.claim_token, call.lease_expires_at = "queued", None, None
    db.add(
        CoordinatorAction(
            user_id=user.id, action="call_retry_transcription", details=f"SIMULATION: Retry call {call.id}"
        )
    )
    db.commit()
    return call_record(db, call)
