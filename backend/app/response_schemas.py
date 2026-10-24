"""Strict contracts for the four published Kontrol CREAO agents."""

from typing import Literal

from pydantic import Field, field_validator

from .schemas import StrictModel


class IntakeResult(StrictModel):
    """Capture the intake agent's interpretation without inventing missing report facts."""

    incident_id: str
    incident_type: str = Field(min_length=2, max_length=100)
    summary: str = Field(min_length=10, max_length=2000)
    reported_injuries: int | None = Field(default=None, ge=0, le=100)
    required_response_types: list[str] = Field(min_length=1, max_length=12)
    reasoning: str = Field(min_length=3, max_length=3000)


class DiscoveredHospital(StrictModel):
    """Represent public hospital facts separately from unknown operational capacity."""

    name: str = Field(min_length=2, max_length=200)
    address: str = Field(min_length=2, max_length=300)
    latitude: float = Field(ge=-90, le=90)
    longitude: float = Field(ge=-180, le=180)
    documented_capabilities: list[str] = Field(max_length=30)
    available_beds: int | None = Field(default=None, ge=0)
    diversion_status: bool | str | None = None
    estimated_travel_minutes: float | None = Field(default=None, ge=0, le=1440)
    travel_time_method: Literal["road_routing", "coordinate_estimate", "unavailable"] | None = None
    source_urls: list[str] = Field(default_factory=list, max_length=20)
    suitability_notes: str = Field(min_length=3, max_length=3000)

    @field_validator("source_urls")
    @classmethod
    def valid_source_urls(cls, values: list[str]) -> list[str]:
        """Allow only absolute HTTP(S) evidence links."""
        if any(not value.startswith(("https://", "http://")) for value in values):
            raise ValueError("source URLs must be absolute HTTP(S) URLs")
        return values


class HospitalResult(StrictModel):
    """Return independently discovered hospitals and explicitly stated limitations."""

    incident_id: str
    hospitals: list[DiscoveredHospital] = Field(max_length=20)
    recommended_hospitals: list[str] = Field(max_length=20)
    reasoning: str = Field(min_length=3, max_length=4000)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class DiscoveredFacility(StrictModel):
    """Store a publicly discovered emergency facility without creating a vehicle."""

    name: str = Field(min_length=2, max_length=200)
    facility_type: str = Field(min_length=2, max_length=100)
    address: str = Field(min_length=2, max_length=300)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source_urls: list[str] = Field(default_factory=list, max_length=20)

    @field_validator("source_urls")
    @classmethod
    def valid_source_urls(cls, values: list[str]) -> list[str]:
        """Allow only absolute HTTP(S) evidence links."""
        if any(not value.startswith(("https://", "http://")) for value in values):
            raise ValueError("source URLs must be absolute HTTP(S) URLs")
        return values


class VehicleRecommendation(StrictModel):
    """Reference one existing Kontrol vehicle and preserve the proposed response role."""

    vehicle_id: str
    response_role: str = Field(min_length=2, max_length=100)
    starting_location: str = Field(min_length=2, max_length=300)
    estimated_arrival_minutes: float | None = Field(default=None, ge=0, le=1440)
    reasoning: str = Field(min_length=3, max_length=3000)


class DispatchResult(StrictModel):
    """Return discovered facilities separately from recommendations for known vehicles."""

    incident_id: str
    discovered_facilities: list[DiscoveredFacility] = Field(default_factory=list, max_length=30)
    recommended_vehicles: list[VehicleRecommendation] = Field(max_length=30)
    unfilled_requirements: list[str] = Field(default_factory=list, max_length=30)
    reasoning: str = Field(min_length=3, max_length=4000)
    limitations: list[str] = Field(default_factory=list, max_length=30)


class HospitalAssignment(StrictModel):
    """Describe a proposed destination without asserting unknown patient capacity."""

    hospital_name: str = Field(min_length=2, max_length=200)
    planned_patient_count: int | None = Field(default=None, ge=0, le=100)
    reasoning: str = Field(min_length=3, max_length=3000)


class VehicleAssignment(StrictModel):
    """Describe a proposed use of one existing vehicle."""

    vehicle_id: str
    response_role: str = Field(min_length=2, max_length=100)
    destination: str = Field(min_length=2, max_length=300)
    reasoning: str = Field(min_length=3, max_length=3000)


class PlanningResult(StrictModel):
    """Combine validated agent findings into a human-reviewable proposal."""

    incident_id: str
    plan_summary: str = Field(min_length=10, max_length=3000)
    hospital_assignments: list[HospitalAssignment] = Field(default_factory=list, max_length=20)
    vehicle_assignments: list[VehicleAssignment] = Field(default_factory=list, max_length=30)
    unfilled_requirements: list[str] = Field(default_factory=list, max_length=30)
    constraints: list[str] = Field(default_factory=list, max_length=30)
    reasoning: str = Field(min_length=3, max_length=4000)
    status: Literal["awaiting_approval", "needs_information"]


class PlanDecision(StrictModel):
    """Protect each human decision against stale plan versions."""

    action: Literal["approve", "reject", "revise"]
    version: int = Field(ge=1)
    note: str = Field(min_length=3, max_length=1000)


class GeneratePlan(StrictModel):
    """Capture the coordinator's reason for manually starting a workflow."""

    note: str = Field(default="Coordinator requested a response plan", min_length=3, max_length=1000)


class DemoControl(StrictModel):
    """Retain isolated mock controls outside the live product workflow."""

    action: Literal["start", "reset"]


STAGE_SCHEMAS = {
    "intake": IntakeResult,
    "hospital": HospitalResult,
    "dispatch": DispatchResult,
    "planning": PlanningResult,
}


def stage_schema(stage: str):
    """Return the exact output model for a known agent stage."""
    if stage not in STAGE_SCHEMAS:
        raise ValueError(f"Unsupported response stage: {stage}")
    return STAGE_SCHEMAS[stage]
