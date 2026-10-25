"""Signed Twilio callbacks and coordinator-only browser phone controls in the existing application."""

import json
import re

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import Response
from pydantic import Field
from sqlalchemy import select

from .call_location import detect_location
from .config import settings
from .db import now
from .dependencies import Coordinator, DB
from .live_calls import end_live_call, live_session
from .models import Call, CoordinatorAction, LiveCallSession, User
from .network import operation_lock
from .schemas import StrictModel
from .telephony_provider import browser_identity, browser_token, hang_up, incoming_twiml, verified_form

router = APIRouter(prefix="/telephony", tags=["Live calls"])
provider_router = APIRouter(prefix="/telephony", tags=["Signed provider callbacks"])
SID = re.compile(r"^CA[0-9a-fA-F]{32}$")


class LiveControl(StrictModel):
    """Use optimistic call versions to prevent competing dispatcher controls."""
    version: int = Field(ge=1)


class ResolveTranscript(LiveControl):
    """Require a deliberate, audited resolution of a failed or partial transcript after hang-up."""
    transcript: str = Field(min_length=10, max_length=4000)
    note: str = Field(min_length=3, max_length=1000)


def current_live(db, call_id: str, version: int | None = None) -> tuple[Call, LiveCallSession]:
    """Lock shared state in the existing operation order and reject missing, deleted or stale calls."""
    operation_lock(db)
    call = db.scalar(select(Call).where(Call.id == call_id).with_for_update().execution_options(populate_existing=True))
    session = live_session(db, call_id)
    if not call or call.status == "deleted" or not session:
        raise HTTPException(404, "Live call not found")
    if version is not None and call.version != version:
        raise HTTPException(409, "Call changed. Refresh before trying again.")
    return call, session


def call_result(db, call: Call) -> dict:
    """Return the same downstream representation used by uploaded recordings."""
    from .call_services import call_record
    return call_record(db, call, include_segments=True)


@router.get("/config")
def configuration(user: Coordinator):
    """Expose feature availability and the assigned number, never provider credentials."""
    return {"enabled": settings.telephony_enabled, "phone_number": settings.twilio_phone_number or None}


@router.post("/token")
def token(user: Coordinator):
    """Mint an incoming-only browser SDK token for the authenticated dispatcher."""
    return {"token": browser_token(user), "identity": browser_identity(user), "expires_in": 600}


@provider_router.post("/incoming")
async def incoming(request: Request, db: DB):
    """Idempotently register an actual inbound call, then route Twilio to registered dispatcher browsers."""
    data = await verified_form(request)
    sid = data.get("CallSid", "")
    if not SID.fullmatch(sid) or data.get("Direction", "inbound") != "inbound":
        raise HTTPException(422, "Expected an inbound provider call")
    if settings.twilio_phone_number and data.get("To") != settings.twilio_phone_number:
        raise HTTPException(403, "Call is not addressed to the configured number")
    operation_lock(db)
    session = db.scalar(select(LiveCallSession).where(LiveCallSession.provider_sid == sid))
    if session:
        call = db.get(Call, session.call_id) if session.call_id else None
        if not call or session.ended_at or call.status == "deleted":
            return Response("<Response><Hangup/></Response>", media_type="application/xml")
    else:
        call = Call(source="live", status="live_ringing", audio_key=None, audio_content_type="audio/wav",
                    duration_seconds=0, simulation=False)
        db.add(call)
        db.flush()
        session = LiveCallSession(call_id=call.id, provider_sid=sid, caller=data.get("From", "Unknown")[:100],
                                  called=data.get("To", "")[:100],
                                  recording_state="pending" if settings.twilio_record_calls else "off")
        db.add(session)
    identities = [browser_identity(user) for user in db.scalars(select(User).where(User.role == "coordinator").limit(5))]
    db.commit()
    return Response(incoming_twiml(call.id, identities), media_type="application/xml")


@provider_router.post("/status/{call_id}")
async def status(call_id: str, request: Request, db: DB):
    """Apply signed child-call events monotonically; a losing parallel browser leg cannot end the winner."""
    data = await verified_form(request)
    call, session = current_live(db, call_id)
    if data.get("ParentCallSid") != session.provider_sid:
        raise HTTPException(403, "Provider call does not match this session")
    state, child = data.get("CallStatus"), data.get("CallSid")
    if not SID.fullmatch(child or ""):
        raise HTTPException(422, "Invalid provider call identifier")
    if not session.ended_at:
        if state == "in-progress":
            if session.browser_sid and session.browser_sid != child:
                return {"ok": True}
            session.browser_sid, session.answered_at, session.state = child, session.answered_at or now(), "active"
            call.status = "live_active"
        elif state in {"completed", "failed", "busy", "no-answer", "canceled"}:
            if session.browser_sid == child:
                end_live_call(db, call, session)
    db.commit()
    return {"ok": True}


@provider_router.post("/ended/{call_id}")
async def ended(call_id: str, request: Request, db: DB):
    """Handle Dial completion whether answered, declined or never connected."""
    data = await verified_form(request)
    call, session = current_live(db, call_id)
    if data.get("CallSid") != session.provider_sid:
        raise HTTPException(403, "Provider call does not match this session")
    end_live_call(db, call, session)
    db.commit()
    return Response("<Response><Hangup/></Response>", media_type="application/xml")


@provider_router.post("/status")
async def parent_status(request: Request, db: DB):
    """Synchronize parent hang-ups, including premature termination before a browser answers."""
    data = await verified_form(request)
    session = db.scalar(select(LiveCallSession).where(LiveCallSession.provider_sid == data.get("CallSid")))
    if session and session.call_id and data.get("CallStatus") in {"completed", "failed", "busy", "no-answer", "canceled"}:
        call, session = current_live(db, session.call_id)
        end_live_call(db, call, session)
        db.commit()
    return {"ok": True}


@router.post("/calls/{call_id}/answer")
def answer(call_id: str, data: LiveControl, db: DB, user: Coordinator):
    """Claim the pending call; only the browser SDK accept operation establishes two-way media."""
    call, session = current_live(db, call_id, data.version)
    if session.ended_at or session.state != "ringing" or session.answered_by:
        raise HTTPException(409, "This call has already been answered or ended.")
    session.answered_by, session.state = user.id, "answering"
    call.status = "live_answering"
    db.add(CoordinatorAction(user_id=user.id, action="live_answer", details=json.dumps({"call_id": call.id})))
    db.commit()
    return call_result(db, call)


@router.post("/calls/{call_id}/{action}")
def control(call_id: str, action: str, data: LiveControl, db: DB, user: Coordinator):
    """End or decline through Twilio, never treating a browser-only state change as a confirmed hang-up."""
    if action not in {"hangup", "decline"}:
        raise HTTPException(404, "Unknown call control")
    call, session = current_live(db, call_id)
    if session.ended_at:
        return call_result(db, call)
    if call.version != data.version:
        raise HTTPException(409, "Call changed. Refresh before trying again.")
    if session.answered_by and session.answered_by != user.id:
        raise HTTPException(409, "Another dispatcher owns this call.")
    provider_sid = session.provider_sid
    db.commit()  # Provider requests must never hold the resource/call locks.
    hang_up(provider_sid)
    call, session = current_live(db, call_id)
    end_live_call(db, call, session, "declined" if action == "decline" else "ended")
    db.add(CoordinatorAction(user_id=user.id, action=f"live_{action}", details=json.dumps({"call_id": call.id})))
    db.commit()
    return call_result(db, call)


@router.post("/resolve/{call_id}")
def resolve(call_id: str, data: ResolveTranscript, db: DB, user: Coordinator):
    """Explicitly accept/correct an incomplete ended transcript without altering original ASR segments."""
    call, session = current_live(db, call_id, data.version)
    if not session.ended_at or call.status != "live_incomplete" or not session.stream_closed_at:
        raise HTTPException(409, "End the call and wait for transcript draining before resolving it.")
    version = call.version
    db.commit()
    location = detect_location(data.transcript)
    call, session = current_live(db, call_id, version)
    session.resolution_text, session.finalized_at = data.transcript, now()
    call.status, call.transcription_error = "awaiting_review", None
    call.detected_location = location.model_dump()
    db.add(CoordinatorAction(user_id=user.id, action="live_transcript_resolved", details=json.dumps({
        "call_id": call.id, "note": data.note, "transcript_changed": data.transcript != call.original_transcript,
    })))
    db.commit()
    return call_result(db, call)


@provider_router.post("/recording/{call_id}")
async def recording(call_id: str, request: Request, db: DB):
    """Retain an account-owned recording reference for durable private download by the worker."""
    data = await verified_form(request)
    call, session = current_live(db, call_id)
    if data.get("CallSid") != session.provider_sid:
        raise HTTPException(403, "Recording does not match this call")
    sid = data.get("RecordingSid", "")
    if not re.fullmatch(r"RE[0-9a-fA-F]{32}", sid):
        raise HTTPException(422, "Invalid recording identifier")
    if (settings.twilio_record_calls and data.get("RecordingStatus") == "completed"
            and session.recording_state not in {"stored", "failed"}):
        session.recording_sid, session.recording_state = sid, "available"
        db.commit()
    return {"ok": True}
