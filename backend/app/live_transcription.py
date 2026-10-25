"""Independent OpenAI Realtime transcription transport for Twilio PCMU tracks; never calls batch ASR."""

import asyncio
import base64
from collections import deque
from dataclasses import dataclass
import json
from typing import Awaitable, Callable, Protocol

from websockets.asyncio.client import connect

from .config import settings


@dataclass(frozen=True)
class TranscriptUpdate:
    """A channel-attributed, media-timestamped partial or final transcription update."""

    item_id: str
    track: str
    start_ms: int
    end_ms: int
    text: str
    final: bool


class StreamingTranscriber(Protocol):
    """Keep live provider transport independent from the existing file transcription adapter."""

    async def append(self, payload: str, timestamp_ms: int) -> None:
        """Append one provider media frame without interrupting phone audio on failure."""
        ...

    async def finish(self) -> None:
        """Commit trailing speech and await final results before closing."""
        ...


def speech_energy(audio: bytes) -> float:
    """Estimate μ-law amplitude for lightweight client turn segmentation, not speaker inference."""
    samples = audio[::8]
    total = 0
    for sample in samples:
        value = ~sample & 255
        magnitude = (((value & 15) << 3) + 132) << ((value & 112) >> 4)
        total += abs(magnitude - 132)
    return total / max(1, len(samples))


class OpenAIStreamingTrack:
    """Transcribe one isolated caller/dispatcher track with explicit commits and completion draining."""

    def __init__(self, track: str, publish: Callable[[TranscriptUpdate], Awaitable[None]]):
        """Initialize bounded turn metadata and server-event deduplication for one provider stream."""
        self.track, self.publish = track, publish
        self.socket = None
        self.reader = None
        self.error = None
        self.turn_start = None
        self.turn_end = 0
        self.last_voice = 0
        self.pending = deque()
        self.items = {}
        self.texts = {}
        self.seen = set()
        self.completed_items = set()
        self.outstanding = 0
        self.drained = asyncio.Event()
        self.drained.set()

    async def open(self) -> None:
        """Open a transcription-only session using separate live credentials and configuration."""
        if not settings.live_transcription_api_key:
            raise RuntimeError("Configure LIVE_TRANSCRIPTION_API_KEY for live speech transcription.")
        if not settings.live_transcription_url.startswith("wss://"):
            raise RuntimeError("Live transcription requires a secure WSS endpoint.")
        self.socket = await connect(settings.live_transcription_url,
                                    additional_headers={"Authorization": f"Bearer {settings.live_transcription_api_key}"},
                                    open_timeout=10, max_size=1024 * 1024)
        try:
            await self.socket.send(json.dumps({
                "type": "session.update", "session": {"type": "transcription", "audio": {"input": {
                    "format": {"type": "audio/pcmu"},
                    "transcription": {"model": settings.live_transcription_model}, "turn_detection": None,
                }}},
            }))
            async with asyncio.timeout(10):
                while True:
                    event = json.loads(await self.socket.recv())
                    if event.get("type") == "error":
                        raise RuntimeError("The live transcription session configuration was rejected.")
                    if event.get("type") in {"session.updated", "transcription_session.updated"}:
                        break
            self.reader = asyncio.create_task(self.receive())
        except Exception:
            await self.socket.close()
            raise

    async def append(self, payload: str, timestamp_ms: int) -> None:
        """Send voiced turns directly as PCMU; silence boundaries and four-second caps trigger commits."""
        if self.error:
            raise RuntimeError(self.error)
        audio = base64.b64decode(payload, validate=True)
        if not audio or len(audio) > 8000:
            raise ValueError("Invalid live audio frame")
        voiced = speech_energy(audio) > 250
        if self.turn_start is None:
            if not voiced:
                return
            self.turn_start = timestamp_ms
        if self.socket is None:
            await self.open()
        self.turn_end = timestamp_ms + len(audio) // 8
        if voiced:
            self.last_voice = self.turn_end
        await self.socket.send(json.dumps({"type": "input_audio_buffer.append", "audio": payload}))
        if self.turn_end - self.turn_start >= 4000 or self.turn_end - self.last_voice >= 600:
            await self.commit()

    async def commit(self) -> None:
        """Associate each explicit committed turn with provider timestamps before asynchronous results arrive."""
        if self.turn_start is None:
            return
        # Realtime requires at least 100 ms. Keep short utterances buffered until more audio arrives.
        if self.turn_end - self.turn_start < 100:
            return
        self.pending.append((self.turn_start, self.turn_end))
        self.outstanding += 1
        self.drained.clear()
        self.turn_start = None
        await self.socket.send(json.dumps({"type": "input_audio_buffer.commit"}))

    async def receive(self) -> None:
        """Persist updates by item ID, tolerating out-of-order final turns but never duplicate event deltas."""
        try:
            async for message in self.socket:
                event = json.loads(message)
                event_id = event.get("event_id")
                if event_id and event_id in self.seen:
                    continue
                if event_id:
                    self.seen.add(event_id)
                if len(self.seen) > 30000:
                    raise ValueError("Live transcription event limit reached")
                kind, item_id = event.get("type"), event.get("item_id")
                if kind in {"error", "conversation.item.input_audio_transcription.failed"}:
                    raise RuntimeError("Live transcription failed; the phone call can continue.")
                if kind == "input_audio_buffer.committed":
                    if not self.pending:
                        raise ValueError("Unexpected live audio commit")
                    self.items[item_id] = self.pending.popleft()
                if kind not in {"conversation.item.input_audio_transcription.delta",
                                "conversation.item.input_audio_transcription.completed"}:
                    continue
                if not isinstance(item_id, str) or len(item_id) > 120:
                    raise ValueError("Invalid transcript item")
                final = kind.endswith(".completed")
                if item_id in self.completed_items:
                    continue
                if item_id not in self.items:
                    # Early live deltas precede commit. Freeze their start so a late delta cannot reorder a turn.
                    start = self.turn_start if self.turn_start is not None else (
                        self.pending[0][0] if self.pending else self.turn_end
                    )
                    self.items[item_id] = (start, self.turn_end)
                start, end = self.items[item_id]
                text = event.get("transcript", "") if final else self.texts.get(item_id, "") + event.get("delta", "")
                if not isinstance(text, str) or len(text) > 10000:
                    raise ValueError("Transcript segment exceeded the text limit")
                self.texts[item_id] = text
                await self.publish(TranscriptUpdate(item_id, self.track, start, end, text, final))
                if final:
                    self.completed_items.add(item_id)
                    self.outstanding = max(0, self.outstanding - 1)
                    if not self.outstanding:
                        self.drained.set()
        except asyncio.CancelledError:
            raise
        except Exception:
            self.error = "Live transcription disconnected or returned invalid data. Review the incomplete transcript."
            self.drained.set()
        finally:
            if self.outstanding:
                self.error = self.error or "Live transcript ended before all speech was finalized."
            self.drained.set()

    async def finish(self) -> None:
        """Flush the last utterance and reject missing completions rather than accepting partial speech."""
        try:
            if self.socket is None:
                return
            if self.turn_start is not None and self.turn_end - self.turn_start < 100:
                # Pad only timing silence, never transcript text, to meet the provider's minimum commit size.
                await self.socket.send(json.dumps({"type": "input_audio_buffer.append",
                                                   "audio": base64.b64encode(b"\xff" * 800).decode()}))
                self.turn_end += 100
            await self.commit()
            await asyncio.wait_for(self.drained.wait(), timeout=15)
            if self.error or self.outstanding or self.pending:
                raise RuntimeError(self.error or "Live transcription has unfinished turns.")
        finally:
            if self.socket is not None:
                await self.socket.close()
            if self.reader:
                self.reader.cancel()
                await asyncio.gather(self.reader, return_exceptions=True)


def get_streaming_transcriber(track: str, publish: Callable[[TranscriptUpdate], Awaitable[None]]) -> StreamingTranscriber:
    """Use the live-only Realtime adapter; uploaded recordings retain their original adapter unchanged."""
    return OpenAIStreamingTrack(track, publish)
