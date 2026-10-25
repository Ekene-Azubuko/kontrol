"""Shared live-call invariants and persisted transcript reconciliation; no batch transcription calls."""

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import now
from .models import Call, LiveCallSession, LiveTranscriptSegment
from .network import record


def live_session(db: Session, call_id: str) -> LiveCallSession | None:
    """Look up the independent provider session linked to a shared call record."""
    return db.scalar(select(LiveCallSession).where(LiveCallSession.call_id == call_id)
                     .execution_options(populate_existing=True))


def require_live_ready(db: Session, call: Call) -> None:
    """Enforce end-of-call and persisted transcript finalization on every downstream entry point."""
    if call.source != "live":
        return
    session = live_session(db, call.id)
    if not session or not session.ended_at or not session.finalized_at:
        raise HTTPException(409, "End the call and finalize its transcript before starting agents or editing review.")


def review_transcript(db: Session, call: Call) -> str | None:
    """Keep an explicit incomplete-transcript resolution separate from original machine segments."""
    session = live_session(db, call.id) if call.source == "live" else None
    return (session.resolution_text if session else None) or call.original_transcript


def live_record(db: Session, call: Call, *, include_segments: bool = False) -> dict | None:
    """Expose private dispatcher state without tokens, storage paths or internal stream credentials."""
    session = live_session(db, call.id)
    if not session:
        return None
    result = record(session, {"recording_sid"})
    result["segments"] = [record(segment) for segment in db.scalars(
        select(LiveTranscriptSegment).where(LiveTranscriptSegment.call_id == call.id)
        .order_by(LiveTranscriptSegment.start_ms, LiveTranscriptSegment.track, LiveTranscriptSegment.item_id)
        .limit(3000)
    )] if include_segments else []
    return result


def end_live_call(db: Session, call: Call, session: LiveCallSession, state: str = "ended") -> None:
    """Apply terminal provider state once without starting agents or treating a stream failure as hang-up."""
    if session.ended_at:
        return
    session.state, session.ended_at = state, now()
    call.status = "live_finalizing"
    if session.answered_at:
        from .db import timestamp

        call.duration_seconds = max(0, timestamp(session.ended_at) - timestamp(session.answered_at))


def transcript_text(db: Session, call_id: str) -> str:
    """Order final speech by provider media timestamps; never promote partial text to final text."""
    segments = db.scalars(select(LiveTranscriptSegment).where(
        LiveTranscriptSegment.call_id == call_id, LiveTranscriptSegment.finalized.is_(True),
    ).order_by(LiveTranscriptSegment.start_ms, LiveTranscriptSegment.track, LiveTranscriptSegment.item_id))
    return "\n".join(
        f"{'Caller' if segment.track == 'inbound' else 'Dispatcher'}: {segment.text.strip()}"
        for segment in segments if segment.text.strip()
    )
