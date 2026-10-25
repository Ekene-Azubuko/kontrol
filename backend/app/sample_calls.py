"""Scripted fiction for a repeatable recorded-call exercise, never emergency guidance."""

from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class SampleCall:
    """Associate a bundled recording with its exact script and approximate caller position."""

    key: str
    title: str
    transcript: str
    latitude: float
    longitude: float

    @property
    def audio_path(self) -> Path:
        """Locate the repository fixture, independent of writable audio storage."""
        return Path(__file__).parent / "fixtures" / "calls" / f"{self.key}.wav"


SAMPLES = {
    item.key: item
    for item in [
        SampleCall(
            "collision",
            "Multi-vehicle collision",
            "This is a simulation. Not for emergency use. Dispatcher: What is the location of the emergency? "
            "Caller: Market and Eighth, in the fictional exercise area. Two vehicles collided. "
            "Two people are reported injured. Dispatcher: I am recording this for the exercise response team.",
            37.778,
            -122.413,
        ),
        SampleCall(
            "cardiac",
            "Reported cardiac arrest",
            "This is a simulation. Not for emergency use. Dispatcher: Where is the emergency? "
            "Caller: The Mission exercise block. One person is unresponsive and not breathing normally. "
            "Dispatcher: This fictional recording ends here. No medical instructions are provided.",
            37.759,
            -122.420,
        ),
        SampleCall(
            "fire",
            "Structure fire",
            "This is a simulation. Not for emergency use. Dispatcher: What is the address? "
            "Caller: The Richmond exercise block. There is a building fire. I do not know if anyone is injured. "
            "Dispatcher: The patient count is unknown. This is a fictional exercise only.",
            37.781,
            -122.459,
        ),
    ]
}
