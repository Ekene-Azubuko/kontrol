"""Validate signed media ingress and Realtime wire events without contacting phone or ASR providers."""

import asyncio
import base64
import json

import pytest
from starlette.websockets import WebSocketDisconnect
from twilio.request_validator import RequestValidator

from app import live_media, live_transcription
from app.config import settings
from app.live_transcription import OpenAIStreamingTrack, TranscriptUpdate
from test_live_calls import (ACCOUNT, PARENT, STREAM, TRANSCRIPT, answer_call, incoming_call)
from test_workflow import COORDINATOR


def test_signed_media_stream_persists_both_tracks_and_deduplicates_frames(live_system, monkeypatch):
    """Forward each actual-format track once, drain final speech, and leave telephone state independent."""
    client, _ = live_system
    call = answer_call(client, incoming_call(client))
    frames = []

    class Track:
        """Stand in only for the remote ASR transport while keeping real ingress and storage code."""

        def __init__(self, track, publish):
            self.track, self.publish = track, publish

        async def append(self, payload, timestamp_ms):
            frames.append((self.track, payload, timestamp_ms))
            await self.publish(TranscriptUpdate("item", self.track, timestamp_ms, timestamp_ms + 100, "Partial", False))

        async def finish(self):
            await self.publish(TranscriptUpdate("item", self.track, 100, 1000,
                                               TRANSCRIPT if self.track == "inbound" else "Where are you?", True))

    monkeypatch.setattr(live_media, "get_streaming_transcriber", Track)
    path = f"/telephony/media/{call['id']}"
    signature = RequestValidator(settings.twilio_auth_token).compute_signature(settings.telephony_public_url + path, {})
    payload = base64.b64encode(b"\x00" * 800).decode()
    with client.websocket_connect(path, headers={"X-Twilio-Signature": signature}) as socket:
        socket.send_json({"event": "connected", "protocol": "Call"})
        socket.send_json({"event": "start", "start": {
            "accountSid": ACCOUNT, "callSid": PARENT, "streamSid": STREAM,
            "mediaFormat": {"encoding": "audio/x-mulaw", "sampleRate": 8000, "channels": 1},
        }})
        for track in ("inbound", "inbound", "outbound"):
            socket.send_json({"event": "media", "streamSid": STREAM,
                              "media": {"track": track, "chunk": "1", "timestamp": "100", "payload": payload}})
        socket.send_json({"event": "stop", "streamSid": STREAM})
        with pytest.raises(WebSocketDisconnect):
            socket.receive_json()
    assert len(frames) == 2
    state = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert {segment["track"] for segment in state["live"]["segments"]} == {"inbound", "outbound"}
    assert all(segment["finalized"] for segment in state["live"]["segments"])
    assert state["live"]["stream_closed_at"] and state["live"]["ended_at"] is None
    assert state["status"] == "live_active"


def test_unsigned_media_never_connects_to_openai(live_system, monkeypatch):
    """Reject unauthenticated audio before allocating a provider transcription connection."""
    client, _ = live_system
    call = incoming_call(client)

    def unexpected(*args):
        raise AssertionError("Unauthorized media must not allocate an ASR session")

    monkeypatch.setattr(live_media, "get_streaming_transcriber", unexpected)
    with pytest.raises(WebSocketDisconnect) as error:
        with client.websocket_connect(f"/telephony/media/{call['id']}"):
            pass
    assert error.value.code == 1008


def test_realtime_transport_keeps_batch_configuration_and_waits_for_final(monkeypatch):
    """Verify real session.update/append/commit shapes, separate live model, and finalized segment emission."""
    monkeypatch.setattr(settings, "live_transcription_api_key", "live-test-key")
    monkeypatch.setattr(settings, "live_transcription_model", "gpt-live-transcribe")
    batch_model = settings.transcription_model
    captured, updates = [], []

    class Socket:
        """Model OpenAI's asynchronous JSON events with a duplicate delta and delayed completion."""

        def __init__(self):
            self.events = asyncio.Queue()

        async def send(self, message):
            event = json.loads(message)
            captured.append(event)
            if event["type"] == "session.update":
                await self.events.put({"type": "session.updated"})
            elif event["type"] == "input_audio_buffer.append":
                delta = {"type": "conversation.item.input_audio_transcription.delta", "event_id": "delta-1",
                         "item_id": "item-1", "delta": "Market"}
                await self.events.put(delta)
                await self.events.put(delta)
            elif event["type"] == "input_audio_buffer.commit":
                await self.events.put({"type": "input_audio_buffer.committed", "item_id": "item-1"})
                await self.events.put({"type": "conversation.item.input_audio_transcription.completed",
                                       "item_id": "item-1", "transcript": TRANSCRIPT})
                await self.events.put({"type": "conversation.item.input_audio_transcription.completed",
                                       "item_id": "item-1", "transcript": TRANSCRIPT})

        async def recv(self):
            return json.dumps(await self.events.get())

        def __aiter__(self):
            return self

        async def __anext__(self):
            return await self.recv()

        async def close(self):
            pass

    async def connect(url, **kwargs):
        assert url.endswith("?intent=transcription")
        assert kwargs["additional_headers"]["Authorization"] == "Bearer live-test-key"
        return Socket()

    async def publish(update):
        updates.append(update)

    async def run():
        track = OpenAIStreamingTrack("inbound", publish)
        await track.append(base64.b64encode(b"\x00" * 800).decode(), 0)
        await track.finish()

    monkeypatch.setattr(live_transcription, "connect", connect)
    asyncio.run(run())
    session = captured[0]["session"]
    assert session["type"] == "transcription"
    assert session["audio"]["input"]["format"] == {"type": "audio/pcmu"}
    assert session["audio"]["input"]["turn_detection"] is None
    assert session["audio"]["input"]["transcription"]["model"] == "gpt-live-transcribe"
    assert settings.transcription_model == batch_model
    assert sum(event["type"] == "input_audio_buffer.commit" for event in captured) == 1
    assert len([update for update in updates if not update.final]) == 1
    assert len([update for update in updates if update.final]) == 1
    assert all(update.start_ms == 0 for update in updates)
    assert updates[-1].final and updates[-1].text == TRANSCRIPT
    assert updates[-1].start_ms == 0 and updates[-1].end_ms == 100
