"""Durable transcription claims that cannot be completed by expired or reset workers."""

from datetime import timedelta
from uuid import uuid4

from sqlalchemy import and_, or_, select
from sqlalchemy.orm import Session

from .call_audio import audio_path
from .call_delete import cleanup_deleted_calls
from .call_location import detect_location
from .config import settings
from .db import SessionLocal, now
from .models import Call
from .network import operation_lock
from .transcription import TranscriptResult, TranscriptionError, get_transcription_adapter


def recover_expired_calls(db: Session) -> None:
    """Expire claims for human retry; a new attempt must never share the old token."""
    for call in db.scalars(
        select(Call)
        .where(Call.status == "transcribing", Call.lease_expires_at < now())
        .with_for_update(skip_locked=True)
    ):
        call.status, call.claim_token, call.lease_expires_at = "failed", None, None
        call.transcription_error = "Transcription lease expired. Review and retry explicitly."


def process_one_call() -> bool:
    """Claim in a short transaction and call the provider without holding database locks."""
    with SessionLocal() as db:
        operation_lock(db)
        cleanup_deleted_calls(db)
        recover_expired_calls(db)
        call = db.scalar(
            select(Call)
            .where(
                or_(
                    Call.status == "queued",
                    and_(Call.status == "awaiting_review", Call.detected_location.is_(None)),
                )
            )
            .order_by(Call.received_at)
            .with_for_update(skip_locked=True)
            .limit(1)
        )
        if not call:
            db.commit()
            return False
        existing_transcript = call.original_transcript if call.status == "awaiting_review" else None
        call.status, call.claim_token = "transcribing", str(uuid4())
        if existing_transcript is None:
            call.attempts += 1
        call.lease_expires_at = now() + timedelta(seconds=settings.transcription_timeout + 30)
        db.commit()
        call_id, token, key, content_type, sample_key = (
            call.id,
            call.claim_token,
            call.audio_key,
            call.audio_content_type,
            call.sample_key,
        )
    output, error, location = None, None, None
    try:
        from .call_services import require_exercise_execution

        if existing_transcript is None:
            require_exercise_execution()
        output = (
            TranscriptResult(text=existing_transcript)
            if existing_transcript is not None
            else TranscriptResult.model_validate(
                get_transcription_adapter().transcribe(audio_path(key), content_type, sample_key).model_dump()
            )
        )
        # Resolve outside locks and persist only with the matching claim, just like transcription.
        location = detect_location(output.text)
    except TranscriptionError as exc:
        error = str(exc)
    except Exception:
        error = "Transcription failed. Check the recording and configuration before retrying."
    with SessionLocal() as db:
        operation_lock(db)
        # Check the lease again: a late result must fail even before the recovery tick runs.
        call = db.scalar(
            select(Call)
            .where(
                Call.id == call_id,
                Call.status == "transcribing",
                Call.claim_token == token,
                Call.lease_expires_at >= now(),
            )
            .with_for_update()
        )
        if call:
            call.status = "failed" if error else "awaiting_review"
            call.transcription_error = error
            if output:
                call.original_transcript = output.text
                call.detected_location = location.model_dump() if location else None
            call.claim_token, call.lease_expires_at = None, None
            db.commit()
    return True
