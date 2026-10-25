"""Exercise real-format signed telephony callbacks and shared downstream review without paid calls."""

from datetime import timedelta
import base64
import json
import io
import wave

import httpx

import pytest
from sqlalchemy import select
from twilio.request_validator import RequestValidator

from app import call_worker, live_media, live_worker, worker
from app.config import settings
from app.db import now
from app.live_calls import live_session
from app.live_transcription import TranscriptUpdate
from app.models import AgentRun, Call, CoordinatorAction, LiveCallSession, LiveTranscriptSegment
from test_workflow import COORDINATOR, RESIDENT

ACCOUNT = "AC" + "a" * 32
PARENT = "CA" + "b" * 32
CHILD = "CA" + "c" * 32
STREAM = "MZ" + "d" * 32
TRANSCRIPT = "Market and Eighth in the fictional exercise area. Two vehicles collided. One person is injured."


def callback(client, path: str, **data):
    """Sign exactly the public URL and form values, as Twilio does for provider callbacks."""
    form = {"AccountSid": ACCOUNT, **data}
    signature = RequestValidator(settings.twilio_auth_token).compute_signature(
        settings.telephony_public_url + path, form,
    )
    return client.post(path, data=form, headers={"X-Twilio-Signature": signature})


def incoming_call(client) -> dict:
    """Register one provider-backed-format incoming call without manufacturing a transcript."""
    response = callback(client, "/telephony/incoming", CallSid=PARENT, From="+14155550100", To="+14155550101")
    assert response.status_code == 200
    assert "<Dial" in response.text and "<Client" in response.text and 'track="both_tracks"' in response.text
    return client.get("/calls", headers=COORDINATOR).json()[0]


def answer_call(client, call: dict) -> dict:
    """Claim then simulate a signed provider answer confirmation, not an agent-start operation."""
    claimed = client.post(f"/telephony/calls/{call['id']}/answer", headers=COORDINATOR,
                          json={"version": call["version"]})
    assert claimed.status_code == 200
    assert callback(client, f"/telephony/status/{call['id']}", ParentCallSid=PARENT,
                    CallSid=CHILD, CallStatus="in-progress").status_code == 200
    return client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()


def finish_stream(factory, call_id: str, *, error: str | None = None) -> None:
    """Persist real-format stream output and drain state; never call the batch adapter."""
    with factory() as db:
        session = live_session(db, call_id)
        session.stream_sid = STREAM
        db.commit()
    live_media.save_update(call_id, STREAM, TranscriptUpdate("turn-1", "inbound", 100, 2000, TRANSCRIPT, True))
    live_media.close_stream(call_id, STREAM, error)


def test_webhooks_and_browser_credentials_are_private(live_system):
    """Unsigned callers cannot create records and residents cannot obtain browser voice credentials."""
    client, factory = live_system
    assert client.post("/telephony/incoming", data={"AccountSid": ACCOUNT, "CallSid": PARENT}).status_code == 403
    assert client.post("/telephony/token", headers=RESIDENT, json={}).status_code == 403
    token = client.post("/telephony/token", headers=COORDINATOR, json={})
    assert token.status_code == 200
    assert "test-api-key-secret" not in token.text and "test-provider-secret" not in token.text
    encoded = token.json()["token"].split(".")[1]
    claims = json.loads(base64.urlsafe_b64decode(encoded + "=" * (-len(encoded) % 4)))
    assert claims["grants"]["voice"]["incoming"]["allow"] is True
    assert "outgoing" not in claims["grants"]["voice"]
    assert 0 < claims["exp"] - now().timestamp() <= 601
    with factory() as db:
        assert db.scalar(select(Call)) is None


def test_public_phone_ingress_cannot_mint_tokens_or_serve_private_calls():
    """The public tunnel exposes only signed provider routes, even with a guessed local demo credential."""
    from fastapi.testclient import TestClient
    from app.telephony_ingress import app

    with TestClient(app) as public:
        assert public.post("/telephony/token", headers=COORDINATOR, json={}).status_code == 404
        assert public.get("/calls", headers=COORDINATOR).status_code == 404
        assert public.get("/docs").status_code == 404


def test_duplicate_incoming_and_answer_never_start_agents(live_system):
    """Duplicate webhook delivery and competing answer clicks do not duplicate calls or create agent work."""
    client, factory = live_system
    call = incoming_call(client)
    duplicate = incoming_call(client)
    assert call["id"] == duplicate["id"]
    answered = answer_call(client, call)
    assert answered["status"] == "live_active"
    assert client.post(f"/telephony/calls/{call['id']}/answer", headers=COORDINATOR,
                       json={"version": answered["version"]}).status_code == 409
    with factory() as db:
        assert len(list(db.scalars(select(Call)))) == 1
        assert db.scalar(select(AgentRun)) is None
    assert call_worker.process_one_call() is False


def test_uploaded_audio_still_uses_original_batch_adapter(live_system, monkeypatch):
    """Coexisting live calls cannot reroute uploaded recordings through streaming or change their ASR inputs."""
    client, _ = live_system
    incoming_call(client)
    sample = client.post("/calls/sample/collision", headers=COORDINATOR).json()
    seen = []
    original = call_worker.get_transcription_adapter()

    class Batch:
        """Record the existing file adapter call and delegate unchanged behavior."""

        def transcribe(self, path, content_type, sample_key):
            seen.append((path, content_type, sample_key))
            return original.transcribe(path, content_type, sample_key)

    monkeypatch.setattr(call_worker, "get_transcription_adapter", Batch)
    assert call_worker.process_one_call()
    assert len(seen) == 1 and seen[0][1:] == ("audio/wav", "collision")
    current = client.get(f"/calls/{sample['id']}", headers=COORDINATOR).json()
    assert current["source"] == "recording" and current["status"] == "awaiting_review"
    assert call_worker.process_one_call() is False


@pytest.mark.parametrize("call_state", ["live_ringing", "live_active", "live_finalizing", "awaiting_review"])
def test_backend_cannot_start_unfinalized_live_calls(live_system, call_state):
    """Even forged ready status, location and transcript cannot bypass the independent live-session barrier."""
    client, factory = live_system
    call = incoming_call(client)
    with factory() as db:
        stored = db.get(Call, call["id"])
        stored.status, stored.original_transcript = call_state, TRANSCRIPT
        if call_state == "live_finalizing":
            live_session(db, call["id"]).ended_at = now()
        db.commit()
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert client.post(f"/calls/{call['id']}/start", headers=COORDINATOR,
                       json={"category": "collision", "version": current["version"]}).status_code == 409
    assert client.post(f"/calls/{call['id']}/confirm-review", headers=COORDINATOR, json={
        "category": "collision", "version": current["version"], "transcript": TRANSCRIPT,
        "address": "Market and Eighth", "latitude": 37.778, "longitude": -122.414,
    }).status_code == 409
    with factory() as db:
        assert db.scalar(select(AgentRun)) is None


def test_ended_live_call_converges_on_existing_four_agent_pipeline(live_system, monkeypatch):
    """Finalized segments enter ordinary review, then only explicit Start Agents creates existing stage jobs."""
    client, factory = live_system
    call = answer_call(client, incoming_call(client))
    finish_stream(factory, call["id"])
    assert live_worker.process_one_live_call() is False  # Stream stop alone is not a telephone hang-up.
    ended = callback(client, f"/telephony/ended/{call['id']}", CallSid=PARENT, DialCallStatus="completed")
    assert ended.status_code == 200
    with factory() as db:
        assert db.scalar(select(AgentRun)) is None
    assert live_worker.process_one_live_call()
    reviewed = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert reviewed["status"] == "awaiting_review"
    assert reviewed["live"]["finalized_at"]
    assert reviewed["original_transcript"] == f"Caller: {TRANSCRIPT}"
    assert reviewed["detected_location"]["status"] == "resolved"
    assert reviewed["has_audio"] is False
    assert client.get(f"/calls/{call['id']}/audio", headers=COORDINATOR).status_code == 404
    with factory() as db:
        assert db.scalar(select(AgentRun)) is None
    assert call_worker.process_one_call() is False
    result = client.post(f"/calls/{call['id']}/start", headers=COORDINATOR,
                         json={"category": "collision", "version": reviewed["version"]})
    assert result.status_code == 200
    assert result.json()["plan_id"]
    for _ in range(4):
        assert worker.process_one()
    plan = client.get(f"/response-plans/{result.json()['plan_id']}", headers=COORDINATOR).json()
    assert len(plan["runs"]) == 4 and all(run["status"] == "completed" for run in plan["runs"])
    assert client.get("/dispatches", headers=COORDINATOR).json() == []
    approved = client.post(f"/response-plans/{plan['id']}/decision", headers=COORDINATOR, json={
        "action": "approve", "version": plan["version"], "note": "Reviewed the completed live-call test plan",
    })
    assert approved.status_code == 200
    assert approved.json()["dispatches"]


def test_transcript_segments_are_ordered_deduplicated_and_partial_safe(live_system):
    """Reordered completions and repeated callbacks never duplicate text or promote unfinished deltas."""
    client, factory = live_system
    call = answer_call(client, incoming_call(client))
    with factory() as db:
        live_session(db, call["id"]).stream_sid = STREAM
        db.commit()
    for update in [
        TranscriptUpdate("later", "outbound", 2000, 2500, "Where are you?", True),
        TranscriptUpdate("earlier", "inbound", 0, 1900, TRANSCRIPT, True),
        TranscriptUpdate("earlier", "inbound", 0, 1900, "duplicate partial", False),
        TranscriptUpdate("unfinished", "inbound", 3000, 4000, "Unfinished speech", False),
    ]:
        live_media.save_update(call["id"], STREAM, update)
    with factory() as db:
        from app.live_calls import transcript_text
        text = transcript_text(db, call["id"])
        assert text.startswith("Caller:") and text.count(TRANSCRIPT) == 1
        assert "duplicate partial" not in text and "Unfinished speech" not in text
        assert len(list(db.scalars(select(LiveTranscriptSegment)))) == 3


def test_failed_transcription_keeps_phone_active_and_requires_resolution(live_system):
    """A transcription outage does not end audio or make agents ready without a dispatcher resolution."""
    client, factory = live_system
    call = answer_call(client, incoming_call(client))
    finish_stream(factory, call["id"], error="Transcription connection lost")
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert current["status"] == "live_active" and not current["live"]["ended_at"]
    assert client.post(f"/telephony/resolve/{call['id']}", headers=COORDINATOR, json={
        "version": current["version"], "transcript": TRANSCRIPT, "note": "Reviewed available speech",
    }).status_code == 409
    callback(client, f"/telephony/ended/{call['id']}", CallSid=PARENT)
    assert live_worker.process_one_live_call()
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert current["status"] == "live_incomplete" and not current["live"]["finalized_at"]
    result = client.post(f"/telephony/resolve/{call['id']}", headers=COORDINATOR, json={
        "version": current["version"], "transcript": TRANSCRIPT, "note": "Reviewed available speech",
    })
    assert result.status_code == 200 and result.json()["live"]["finalized_at"]
    assert result.json()["status"] == "awaiting_review"
    with factory() as db:
        assert db.scalar(select(CoordinatorAction).where(CoordinatorAction.action == "live_transcript_resolved"))
        assert db.scalar(select(AgentRun)) is None


def test_missing_stream_and_premature_hangup_are_incomplete(live_system):
    """Lost media connections after caller hang-up cannot become empty ready transcripts."""
    client, factory = live_system
    call = incoming_call(client)
    callback(client, "/telephony/status", CallSid=PARENT, CallStatus="completed")
    with factory() as db:
        live_session(db, call["id"]).ended_at = now() - timedelta(seconds=60)
        db.commit()
    assert live_worker.process_one_live_call()
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert current["status"] == "live_incomplete"
    assert not current["live"]["finalized_at"]


def test_losing_browser_status_and_late_events_cannot_end_or_revive_call(live_system):
    """Signed but reordered child events cannot terminate the winning browser or resurrect ended state."""
    client, _ = live_system
    call = answer_call(client, incoming_call(client))
    callback(client, f"/telephony/status/{call['id']}", ParentCallSid=PARENT,
             CallSid="CA" + "e" * 32, CallStatus="completed")
    assert client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()["status"] == "live_active"
    callback(client, f"/telephony/ended/{call['id']}", CallSid=PARENT)
    callback(client, f"/telephony/status/{call['id']}", ParentCallSid=PARENT,
             CallSid=CHILD, CallStatus="in-progress")
    assert client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()["status"] == "live_finalizing"


def test_live_delete_preserves_provider_tombstone(live_system):
    """A duplicate incoming callback after deletion cannot recreate a private recording or queue entry."""
    client, factory = live_system
    call = incoming_call(client)
    assert client.request("DELETE", f"/calls/{call['id']}", headers=COORDINATOR,
                          json={"version": call["version"]}).status_code == 409
    callback(client, f"/telephony/ended/{call['id']}", CallSid=PARENT)
    with factory() as db:
        live_session(db, call["id"]).stream_closed_at = now()
        db.commit()
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    deleted = client.request("DELETE", f"/calls/{call['id']}", headers=COORDINATOR,
                             json={"version": current["version"]})
    assert deleted.status_code == 200
    callback(client, "/telephony/incoming", CallSid=PARENT, From="+14155550100", To="+14155550101")
    assert client.get("/calls", headers=COORDINATOR).json() == []
    with factory() as db:
        assert db.scalar(select(LiveCallSession)).call_id is None


@pytest.mark.parametrize("redirect", [False, True])
def test_optional_recording_uses_private_storage_without_batch_asr(live_system, monkeypatch, redirect):
    """Download only the validated account recording and expose playback through existing authorization."""
    client, _ = live_system
    monkeypatch.setattr(settings, "twilio_record_calls", True)
    call = incoming_call(client)
    recording_sid = "RE" + "f" * 32
    response = callback(client, f"/telephony/recording/{call['id']}", CallSid=PARENT,
                        RecordingSid=recording_sid, RecordingStatus="completed", RecordingUrl="https://untrusted.invalid")
    assert response.status_code == 200
    audio = io.BytesIO()
    with wave.open(audio, "wb") as output:
        output.setnchannels(2)
        output.setsampwidth(2)
        output.setframerate(8000)
        output.writeframes(b"\x00" * 32000)

    def download(request):
        if request.url.host == "audio-test.s3.amazonaws.com":
            assert "authorization" not in request.headers
            return httpx.Response(200, content=audio.getvalue())
        assert request.url.host == "api.twilio.com"
        assert request.url.path.endswith(f"/{recording_sid}.wav")
        assert request.headers["authorization"].startswith("Basic ")
        if redirect:
            return httpx.Response(302, headers={"location": "https://audio-test.s3.amazonaws.com/recording.wav"})
        return httpx.Response(200, content=audio.getvalue())

    original = httpx.Client
    monkeypatch.setattr(live_worker.httpx, "Client", lambda **kwargs: original(
        transport=httpx.MockTransport(download), **kwargs,
    ))
    assert live_worker.retain_one_live_recording()
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert current["has_audio"] and "audio_key" not in current
    assert current["live"]["recording_state"] == "stored"
    assert client.get(f"/calls/{call['id']}/audio", headers=COORDINATOR).content == audio.getvalue()
    assert client.get(f"/calls/{call['id']}/audio", headers=RESIDENT).status_code == 403
    assert call_worker.process_one_call() is False
