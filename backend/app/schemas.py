"""Strict schemas at resident, coordinator and external-agent boundaries."""

from datetime import UTC, datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator

Category = Literal["wildfire", "smoke", "road", "medical", "power", "water", "collision", "fire", "rescue"]
Severity = Literal["low", "moderate", "high", "critical"]


class StrictModel(BaseModel):
    """Reject unexpected fields rather than silently trusting agent output."""

    model_config = ConfigDict(extra="forbid")


class ReportInput(StrictModel):
    """Validate an original observation without treating it as verified fact."""

    category: Category
    description: str = Field(min_length=10, max_length=4000)
    reported_casualties: int | None = Field(default=None, ge=0, le=100)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    location: str = Field(min_length=2, max_length=160)
    observed_at: datetime
    photo: str | None = Field(default=None, max_length=1400000)

    @field_validator("observed_at")
    @classmethod
    def observation_not_future(cls, value: datetime) -> datetime:
        """Reject ambiguous timezone or future observation timestamps."""
        if value.tzinfo is None or value > datetime.now(UTC):
            raise ValueError("Observation must have a timezone and cannot be in the future")
        return value

    @field_validator("photo")
    @classmethod
    def image_only(cls, value: str | None) -> str | None:
        """Allow bounded raster data URLs, never executable SVG or remote URLs."""
        if value and not value.startswith(
            ("data:image/jpeg;base64,", "data:image/png;base64,", "data:image/webp;base64,")
        ):
            raise ValueError("Photo must be a JPEG, PNG or WebP image")
        return value


class Assessment(StrictModel):
    """Shared bounded contract for every agent, without authority-bearing fields."""

    category: Category
    severity: Severity
    summary: str = Field(min_length=10, max_length=2000)
    confidence: float = Field(ge=0, le=1)
    evidence_report_ids: list[str] = Field(max_length=30)
    contradictions: list[str] = Field(max_length=20)
    missing_information: list[str] = Field(max_length=20)
    recommended_actions: list[str] = Field(max_length=10)


class IncidentAction(StrictModel):
    """Require the version reviewed by the coordinator to prevent lost updates."""

    action: Literal["verify", "dispute", "resolve", "reopen", "assign", "merge"]
    version: int = Field(ge=1)
    note: str = Field(min_length=3, max_length=1000)
    target_id: str | None = None


class UpdateInput(StrictModel):
    """A draft message is never implicitly published."""

    incident_id: str
    title: str = Field(min_length=3, max_length=160)
    body: str = Field(min_length=10, max_length=4000)
    audience: str = Field(min_length=2, max_length=100)


class ResourceInput(StrictModel):
    """Validate capacity changes as one atomic versioned edit."""

    capacity: int = Field(ge=0, le=100000)
    occupancy: int = Field(ge=0, le=100000)
    published: bool
    version: int


class RequestInput(StrictModel):
    """Propose an allocation without granting dispatch authority."""

    incident_id: str
    resource_id: str
    quantity: int = Field(ge=1, le=10000)
    rationale: str = Field(min_length=3, max_length=1000)


class Question(StrictModel):
    """Bound assistant input and retain explicit geographic context."""

    question: str = Field(min_length=3, max_length=1000)


class SimulationInput(StrictModel):
    """Limit replay controls and speed to a small predictable range."""

    action: Literal["start", "pause", "reset", "speed"]
    speed: int = Field(default=1, ge=1, le=10)
