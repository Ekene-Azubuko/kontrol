"""Private audio storage and bounded media inspection for untrusted uploads."""

import json
import math
import subprocess
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile

from .config import settings

CONTENT_TYPES = {
    "audio/wav": ".wav",
    "audio/x-wav": ".wav",
    "audio/wave": ".wav",
    "audio/mpeg": ".mp3",
    "audio/mp3": ".mp3",
    "audio/webm": ".webm",
    "audio/ogg": ".ogg",
}


def audio_path(key: str) -> Path:
    """Resolve only server-generated basenames inside private storage."""
    if Path(key).name != key or not key or key.startswith("."):
        raise HTTPException(404, "Recording not found")
    return Path(settings.call_audio_dir) / key


def inspect_audio(path: Path) -> tuple[str, float]:
    """Check local media format and duration without allowing network protocols or playlists."""
    try:
        result = subprocess.run(
            [
                "ffprobe",
                "-v",
                "error",
                "-protocol_whitelist",
                "file",
                "-format_whitelist",
                "wav,mp3,matroska,webm,ogg",
                "-show_entries",
                "format=format_name,duration:stream=codec_type,duration",
                "-of",
                "json",
                str(path),
            ],
            capture_output=True,
            timeout=5,
            check=True,
        )
        metadata = json.loads(result.stdout)
        streams = metadata.get("streams", [])
        if not streams or any(s["codec_type"] != "audio" for s in streams):
            raise ValueError("Audio only")
        names = set(metadata["format"]["format_name"].split(","))
        content_type = next(
            (
                mime
                for name, mime in [
                    ("wav", "audio/wav"),
                    ("mp3", "audio/mpeg"),
                    ("webm", "audio/webm"),
                    ("ogg", "audio/ogg"),
                ]
                if name in names
            ),
            None,
        )
        duration = float(metadata["format"].get("duration", streams[0].get("duration", "nan")))
        if (
            not content_type
            or not math.isfinite(duration)
            or not 0 < duration <= settings.call_max_duration_seconds
        ):
            raise ValueError("Invalid format or duration")
        return content_type, duration
    except (subprocess.SubprocessError, OSError, ValueError, KeyError, TypeError, IndexError):
        raise HTTPException(
            422, "Choose decodable WAV, MP3, WebM or Ogg audio within the configured duration limit."
        ) from None


def save_upload(upload: UploadFile) -> tuple[str, str, float]:
    """Copy incrementally, inspect and remove every rejected or partially written file."""
    suffix = CONTENT_TYPES.get(upload.content_type or "")
    if not suffix:
        raise HTTPException(422, "Choose WAV, MP3, WebM or Ogg audio.")
    key = f"{uuid4()}{suffix}"
    path = audio_path(key)
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        size = 0
        with path.open("xb") as destination:
            while chunk := upload.file.read(65536):
                size += len(chunk)
                if size > settings.call_max_audio_bytes:
                    raise HTTPException(413, "Recording exceeds CALL_MAX_AUDIO_BYTES.")
                destination.write(chunk)
        content_type, duration = inspect_audio(path)
        # Use detected media rather than the caller's claimed extension for provider uploads.
        detected = path.with_suffix(CONTENT_TYPES[content_type])
        path.rename(detected)
        return detected.name, content_type, duration
    except Exception:
        path.unlink(missing_ok=True)
        raise
