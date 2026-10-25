"""Regenerate committed fictional audio on macOS; never required for demo startup."""

import subprocess
import sys
import tempfile
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from app.sample_calls import SAMPLES  # noqa: E402


def main() -> None:
    """Speak the exact mock scripts and verify the encoder produced nonempty recordings."""
    with tempfile.TemporaryDirectory(prefix="kontrol-audio-") as directory:
        for sample in SAMPLES.values():
            temporary = Path(directory) / f"{sample.key}.aiff"
            subprocess.run(
                ["say", "-v", "Samantha", "-r", "165", "-o", str(temporary), sample.transcript], check=True
            )
            subprocess.run(
                [
                    "ffmpeg",
                    "-y",
                    "-v",
                    "error",
                    "-i",
                    str(temporary),
                    "-ar",
                    "16000",
                    "-ac",
                    "1",
                    str(sample.audio_path),
                ],
                check=True,
            )
            if sample.audio_path.stat().st_size < 1000:
                raise RuntimeError(
                    "Speech service produced empty audio; run with access to the macOS speech service"
                )


if __name__ == "__main__":
    main()
