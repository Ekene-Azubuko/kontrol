"""Authenticated Twilio media ingress, with transcription failures isolated from two-way phone audio."""

import asyncio
import json
from datetime import timedelta

from fastapi import APIRouter, WebSocket
from sqlalchemy import select
from twilio.request_validator import RequestValidator

from .config import settings
from .db import SessionLocal, now
from .live_calls import live_session
from .live_transcription import TranscriptUpdate, get_streaming_transcriber
from .models import Call, LiveTranscriptSegment
from .network import operation_lock
from .telephony_provider import public_url

router = APIRouter()


def save_update(call_id: str, stream_sid: str, update: TranscriptUpdate) -> None:
    """Persist each item idempotently; deleted calls, replaced streams and final text cannot be revived."""
    with SessionLocal() as db:
        operation_lock(db)
        call = db.get(Call, call_id)
        session = live_session(db, call_id)
        if not call or call.status == "deleted" or not session or session.stream_sid != stream_sid or session.finalized_at:
            return
        segment = db.scalar(select(LiveTranscriptSegment).where(
            LiveTranscriptSegment.call_id == call_id, LiveTranscriptSegment.track == update.track,
            LiveTranscriptSegment.item_id == update.item_id,
        ))
        if not segment:
            segment = LiveTranscriptSegment(call_id=call_id, track=update.track, item_id=update.item_id,
                                            start_ms=update.start_ms, end_ms=update.end_ms)
            db.add(segment)
        elif segment.finalized:
            return
        segment.start_ms, segment.end_ms = update.start_ms, update.end_ms
        segment.text, segment.finalized = update.text, update.final
        session.stream_heartbeat = now()
        db.commit()


def close_stream(call_id: str, stream_sid: str, error: str | None) -> None:
    """Mark stream drain completion without declaring the separate telephone call ended."""
    with SessionLocal() as db:
        operation_lock(db)
        session = live_session(db, call_id)
        if session and session.stream_sid == stream_sid:
            session.stream_closed_at = now()
            if error:
                session.transcription_error = error
            db.commit()


@router.websocket("/telephony/media/{call_id}")
async def media_stream(websocket: WebSocket, call_id: str):
    """Validate the signed handshake and parent account/call before forwarding bounded PCMU frames."""
    if not settings.telephony_enabled or not settings.twilio_auth_token:
        await websocket.close(code=1008)
        return
    signature = websocket.headers.get("x-twilio-signature", "")
    canonical = public_url(websocket.url.path)
    validator = RequestValidator(settings.twilio_auth_token)
    # Twilio deployments sign the public upgrade URL; allow only its HTTPS/WSS forms and trailing slash.
    urls = [canonical, canonical + "/", canonical.replace("https://", "wss://", 1),
            canonical.replace("https://", "wss://", 1) + "/"]
    if not any(validator.validate(url, {}, signature) for url in urls):
        await websocket.close(code=1008)
        return
    await websocket.accept()
    stream_sid, failure, stopped = None, None, False
    tracks = {}
    last_chunk = {}
    try:
        async with asyncio.timeout(10):
            while True:
                message = await websocket.receive_text()
                if len(message) > 65536:
                    raise ValueError("Media message too large")
                data = json.loads(message)
                if data.get("event") == "start":
                    break
        start = data["start"]
        if start.get("accountSid") != settings.twilio_account_sid:
            raise ValueError("Invalid media account")
        with SessionLocal() as db:
            operation_lock(db)
            call = db.get(Call, call_id)
            session = live_session(db, call_id)
            media = start.get("mediaFormat", {})
            if (not call or call.status == "deleted" or not session or session.ended_at or session.stream_sid
                    or start.get("callSid") != session.provider_sid
                    or media.get("encoding") != "audio/x-mulaw" or media.get("sampleRate") != 8000
                    or media.get("channels") != 1):
                raise ValueError("Media stream does not match a pending live call")
            stream_sid = start["streamSid"]
            session.stream_sid, session.stream_heartbeat = stream_sid, now()
            db.commit()

        async def publish(update: TranscriptUpdate) -> None:
            """Keep synchronous database writes outside the WebSocket event loop."""
            await asyncio.to_thread(save_update, call_id, stream_sid, update)

        tracks = {track: get_streaming_transcriber(track, publish) for track in ("inbound", "outbound")}
        failed_tracks = set()
        active = False
        while True:
            message = await asyncio.wait_for(websocket.receive_text(), timeout=60)
            if len(message) > 65536:
                raise ValueError("Media message too large")
            data = json.loads(message)
            if data.get("streamSid") != stream_sid:
                raise ValueError("Media stream identity changed")
            if data.get("event") == "stop":
                stopped = True
                break
            if data.get("event") != "media":
                continue
            if not active:
                with SessionLocal() as db:
                    session = live_session(db, call_id)
                    active = bool(session and session.answered_at)
                if not active:
                    continue  # Ringback is not dispatcher speech.
            media = data["media"]
            track, chunk = media["track"], int(media["chunk"])
            if track not in tracks or chunk <= last_chunk.get(track, 0):
                continue
            if track in last_chunk and chunk != last_chunk[track] + 1:
                failure = "Some live audio frames were missing. Review the incomplete transcript."
            last_chunk[track] = chunk
            if track in failed_tracks:
                continue
            try:
                timestamp = int(media["timestamp"])
                if timestamp < 0 or timestamp > 4 * 60 * 60 * 1000:
                    raise ValueError("Media timestamp out of bounds")
                await tracks[track].append(media["payload"], timestamp)
            except Exception:
                failed_tracks.add(track)
                failure = "Live transcription was interrupted. The phone call can continue; resolve the transcript after hang-up."
                with SessionLocal() as db:
                    session = live_session(db, call_id)
                    if session:
                        session.transcription_error = failure
                        db.commit()
    except Exception:
        failure = "The live audio stream disconnected before a clean end. Review the incomplete transcript."
    finally:
        results = await asyncio.gather(*(track.finish() for track in tracks.values()), return_exceptions=True)
        if any(isinstance(result, BaseException) for result in results):
            failure = failure or "Some live speech was not finalized. Resolve the incomplete transcript."
        if stream_sid:
            await asyncio.to_thread(close_stream, call_id, stream_sid,
                                    failure if failure or stopped else "Live stream interrupted")
        try:
            await websocket.close()
        except RuntimeError:
            pass


def recover_missing_streams(db) -> None:
    """Convert lost/draining streams to an explicit incomplete state after the end-of-call grace period."""
    from .models import LiveCallSession

    deadline = now() - timedelta(seconds=settings.live_finalization_timeout)
    for session in db.scalars(select(LiveCallSession).where(
        LiveCallSession.ended_at < deadline, LiveCallSession.finalized_at.is_(None),
        LiveCallSession.stream_closed_at.is_(None),
    )):
        session.stream_closed_at = now()
        session.transcription_error = "No complete audio stream was received. Resolve the incomplete transcript."
