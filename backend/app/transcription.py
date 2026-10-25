"""Bounded speech-to-text behind deterministic mock and documented HTTP adapters."""

import unicodedata
from pathlib import Path
from typing import Protocol

import httpx
from pydantic import Field, field_validator

from .config import settings
from .sample_calls import SAMPLES
from .schemas import StrictModel


class TranscriptionError(Exception):
    """An actionable error safe to expose without provider responses or credentials."""


class TranscriptResult(StrictModel):
    """Validate a bounded transcript before storing or displaying external text."""

    text: str = Field(min_length=10, max_length=4000)

    @field_validator("text")
    @classmethod
    def clean_text(cls, value: str) -> str:
        """Strip invisible controls while retaining readable line breaks and spacing."""
        value = "".join(
            c for c in value if c in "\n\t" or not unicodedata.category(c).startswith("C")
        ).strip()
        if len(value) < 10:
            raise ValueError("Transcript is empty or too short")
        return value


class TranscriptionAdapter(Protocol):
    """Keep provider-specific requests outside durable job orchestration."""

    def transcribe(self, audio: Path, content_type: str, sample_key: str | None) -> TranscriptResult:
        """Return validated text for a local recording."""
        ...


class MockTranscription:
    """Return exact bundled scripts; never invent words for arbitrary uploaded recordings."""

    def transcribe(self, audio: Path, content_type: str, sample_key: str | None) -> TranscriptResult:
        """Fail clearly unless the recording was injected from a known sample."""
        if sample_key not in SAMPLES:
            raise TranscriptionError(
                "Transcription supports bundled samples only in mock mode. Load a sample or enable live transcription."
            )
        return TranscriptResult(text=SAMPLES[sample_key].transcript)


class LiveTranscription:
    """Use the documented OpenAI-compatible multipart audio transcription contract."""

    def transcribe(self, audio: Path, content_type: str, sample_key: str | None) -> TranscriptResult:
        """Bound network time and response bytes without exposing remote errors."""
        if not settings.transcription_api_key:
            raise TranscriptionError("Configure TRANSCRIPTION_API_KEY before retrying live transcription.")
        try:
            with (
                audio.open("rb") as recording,
                httpx.Client(timeout=settings.transcription_timeout) as client,
            ):
                with client.stream(
                    "POST",
                    f"{settings.transcription_base_url.rstrip('/')}/audio/transcriptions",
                    headers={"Authorization": f"Bearer {settings.transcription_api_key}"},
                    files={"file": (f"recording{audio.suffix}", recording, content_type)},
                    data={"model": settings.transcription_model, "response_format": "json"},
                ) as response:
                    response.raise_for_status()
                    body = bytearray()
                    for chunk in response.iter_bytes(chunk_size=8192):
                        body.extend(chunk)
                        if len(body) > 65536:
                            raise TranscriptionError(
                                "Transcription response is too large. Use a shorter recording."
                            )
            import json

            result = json.loads(body)
            # The provider may include documented metadata; only text crosses our internal boundary.
            return TranscriptResult(text=result["text"])
        except TranscriptionError:
            raise
        except Exception:
            raise TranscriptionError(
                "Live transcription failed or returned invalid text. Check configuration or use a shorter recording, then retry."
            ) from None


def get_transcription_adapter() -> TranscriptionAdapter:
    """Select a provider explicitly; misspelled modes must fail closed."""
    if settings.transcription_mode == "mock":
        return MockTranscription()
    if settings.transcription_mode == "live":
        return LiveTranscription()
    raise TranscriptionError("TRANSCRIPTION_MODE must be mock or live.")
