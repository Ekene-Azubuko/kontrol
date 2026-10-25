"""Finalize ended live calls into existing review records and retain optional provider recordings privately."""

from datetime import timedelta
from uuid import uuid4
from urllib.parse import urlparse
import wave

import httpx
from sqlalchemy import select

from .call_audio import audio_path
from .call_location import detect_location, unavailable
from .config import settings
from .db import SessionLocal, now, timestamp
from .live_calls import transcript_text
from .live_media import recover_missing_streams
from .models import Call, LiveCallSession
from .network import operation_lock


def process_one_live_call() -> bool:
    """Claim only ended live calls, reconcile final segments and reuse the existing location/review workflow."""
    with SessionLocal() as db:
        operation_lock(db)
        recover_missing_streams(db)
        # A crashed finalizer cannot leave the call indefinitely eligible or ready with partial speech.
        for expired in db.scalars(select(Call).where(
            Call.source == "live", Call.status == "live_finalizing", Call.claim_token.is_not(None),
            Call.lease_expires_at < now(),
        )):
            expired.status, expired.claim_token, expired.lease_expires_at = "live_incomplete", None, None
            expired.transcription_error = "Live transcript finalization was interrupted. Resolve it explicitly."
        call = db.scalar(select(Call).join(LiveCallSession, LiveCallSession.call_id == Call.id).where(
            Call.source == "live", Call.status == "live_finalizing", Call.claim_token.is_(None),
            LiveCallSession.ended_at.is_not(None), LiveCallSession.stream_closed_at.is_not(None),
            LiveCallSession.finalized_at.is_(None),
        ).with_for_update(skip_locked=True, of=Call).limit(1))
        if not call:
            db.commit()
            return False
        session = db.scalar(select(LiveCallSession).where(LiveCallSession.call_id == call.id))
        text = transcript_text(db, call.id)
        call.original_transcript = text or None
        if session.transcription_error or not 10 <= len(text) <= 4000:
            call.status = "live_incomplete"
            call.transcription_error = session.transcription_error or (
                "The final transcript is empty, too short, or exceeds 4,000 characters. Review and resolve it explicitly."
            )
            db.commit()
            return True
        call.claim_token, call.lease_expires_at = str(uuid4()), now() + timedelta(seconds=120)
        call_id, token = call.id, call.claim_token
        db.commit()
    try:
        location = detect_location(text)
    except Exception:
        location = unavailable("Location could not be resolved. Use the existing address correction controls.")
    with SessionLocal() as db:
        operation_lock(db)
        call = db.scalar(select(Call).where(
            Call.id == call_id, Call.status == "live_finalizing", Call.claim_token == token,
            Call.lease_expires_at >= now(),
        ).with_for_update())
        if call:
            session = db.scalar(select(LiveCallSession).where(LiveCallSession.call_id == call.id))
            session.finalized_at = now()
            call.detected_location, call.status = location.model_dump(), "awaiting_review"
            call.transcription_error, call.claim_token, call.lease_expires_at = None, None, None
            db.commit()
    return True


def retain_one_live_recording() -> bool:
    """Fetch one account-owned recording without ever invoking batch transcription on live audio."""
    with SessionLocal() as db:
        for expired in db.scalars(select(LiveCallSession).where(
            LiveCallSession.recording_state == "downloading",
            LiveCallSession.recording_claimed_at < now() - timedelta(seconds=90),
        ).with_for_update(skip_locked=True)):
            expired.recording_state = "available" if expired.recording_attempts < 3 else "failed"
        db.flush()
        call = db.scalar(select(Call).join(LiveCallSession, LiveCallSession.call_id == Call.id).where(
            Call.source == "live", Call.status != "deleted", Call.audio_key.is_(None),
            LiveCallSession.recording_state == "available", LiveCallSession.recording_attempts < 3,
        ).with_for_update(skip_locked=True, of=Call).limit(1))
        if not call:
            db.commit()
            return False
        session = db.scalar(select(LiveCallSession).where(LiveCallSession.call_id == call.id))
        session.recording_attempts += 1
        session.recording_state, session.recording_claimed_at = "downloading", now()
        claim_time = timestamp(session.recording_claimed_at)
        call_id, sid = call.id, session.recording_sid
        db.commit()
    key = f"{uuid4()}.wav"
    path = audio_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        # Build the URL from a validated SID rather than trusting a callback-supplied recording URL.
        url = f"https://api.twilio.com/2010-04-01/Accounts/{settings.twilio_account_sid}/Recordings/{sid}.wav"
        with httpx.Client(timeout=20, auth=(settings.twilio_account_sid, settings.twilio_auth_token)) as client:
            with client.stream("GET", url) as response:
                if response.is_redirect:
                    target = response.headers.get("location", "")
                    parsed = urlparse(target)
                    if parsed.scheme != "https" or not (parsed.hostname or "").endswith((".amazonaws.com", ".twiliocdn.com")):
                        raise ValueError("Untrusted provider recording redirect")
                    # Credentials stay with Twilio; signed recording storage gets a clean anonymous client.
                    with httpx.Client(timeout=20) as storage:
                        with storage.stream("GET", target) as audio:
                            write_recording(audio, path)
                else:
                    write_recording(response, path)
        with wave.open(str(path), "rb") as recording:
            duration = recording.getnframes() / recording.getframerate()
        with SessionLocal() as db:
            operation_lock(db)
            call = db.get(Call, call_id)
            if not call or call.status == "deleted":
                path.unlink(missing_ok=True)
                return True
            session = db.scalar(select(LiveCallSession).where(LiveCallSession.call_id == call.id))
            if (not session or session.recording_state != "downloading" or not session.recording_claimed_at
                    or timestamp(session.recording_claimed_at) != claim_time or call.audio_key):
                path.unlink(missing_ok=True)
                return True
            call.audio_key, call.audio_content_type, call.duration_seconds = key, "audio/wav", duration
            session.recording_state = "stored"
            db.commit()
    except Exception:
        path.unlink(missing_ok=True)
        with SessionLocal() as db:
            session = db.scalar(select(LiveCallSession).where(LiveCallSession.call_id == call_id))
            if (session and session.recording_state == "downloading" and session.recording_claimed_at
                    and timestamp(session.recording_claimed_at) == claim_time):
                session.recording_state = "failed" if session.recording_attempts >= 3 else "available"
                db.commit()
    return True


def write_recording(response: httpx.Response, path) -> None:
    """Stream a provider recording into a private, bounded file without loading arbitrary audio into memory."""
    response.raise_for_status()
    size = 0
    with path.open("xb") as destination:
        for chunk in response.iter_bytes(65536):
            size += len(chunk)
            if size > settings.call_max_audio_bytes:
                raise ValueError("Provider recording exceeds the configured storage limit")
            destination.write(chunk)


def live_maintenance() -> bool:
    """Keep finalization independent of batch transcription latency and process optional recordings afterward."""
    return process_one_live_call() or retain_one_live_recording()
