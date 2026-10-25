"""Validate canonical artifacts without trusting their MIME type or weakening agent schemas."""

import json

import httpx
import pytest
from pydantic import ValidationError

from app.creao import validate_completed_result


RESULTS = {
    "intake": {
        "incident_id": "incident-1", "incident_type": "vehicle_collision",
        "summary": "Two cars collided and no injuries were reported.",
        "reported_injuries": 0, "required_response_types": ["police"],
        "reasoning": "Traffic control is needed.",
        "limitations": [], "status": None, "caller_stated_location": None, "key_statements": [],
    },
    "hospital": {
        "incident_id": "incident-1", "hospitals": [], "recommended_hospitals": [],
        "reasoning": "No injured patients were reported.", "limitations": [],
    },
    "dispatch": {
        "incident_id": "incident-1", "discovered_facilities": [],
        "recommended_vehicles": [], "unfilled_requirements": ["police"],
        "reasoning": "No police vehicle is available.", "limitations": [],
    },
    "planning": {
        "incident_id": "incident-1", "plan_summary": "Await a police unit for traffic control.",
        "schema_version": None, "incident_type": None, "location": None,
        "limitations": [], "planned_patient_count": None, "vehicle_assignment_count": None,
        "hospital_assignments": [], "vehicle_assignments": [],
        "unfilled_requirements": ["police"], "constraints": ["No available unit"],
        "reasoning": "An available police vehicle is required.", "status": "needs_information",
    },
}


def download_result(stage: str, body: str):
    """Mock the authenticated artifact download while retaining real response parsing."""
    def download(request: httpx.Request) -> httpx.Response:
        """Serve a mislabeled CREAO artifact through the configured trusted origin."""
        assert request.url.host == "agent.creao.ai"
        assert request.headers["authorization"] == "Bearer test-token"
        return httpx.Response(200, text=body, headers={"Content-Type": "application/json"})

    with httpx.Client(
        base_url="https://agent.creao.ai",
        headers={"Authorization": "Bearer test-token"},
        transport=httpx.MockTransport(download),
    ) as client:
        return validate_completed_result(stage, {
            "text": "Summary only; the artifact contains the complete result.",
            "artifacts": [{"url": "https://agent.creao.ai/artifacts/result", "type": "application/json"}],
        }, client)


@pytest.mark.parametrize("stage", RESULTS)
@pytest.mark.parametrize("wrapper", ["bare", "fence", "prose", "unfenced_prose", "string_json", "string_fence"])
def test_artifact_formats_validate_for_every_stage(stage, wrapper):
    """Accept the observed prose-wrapped artifact and existing supported JSON encodings."""
    expected = RESULTS[stage]
    encoded = json.dumps(expected)
    fence = f"```json\n{encoded}\n```"
    bodies = {
        "bare": encoded,
        "fence": fence,
        "prose": f"` (also saved at `files/result.json`).\n\n{fence}\n\nUnverified report.",
        "unfenced_prose": f"Inputs validated. Now evaluating supplied data.{encoded}\nUnverified report.",
        "string_json": json.dumps(encoded),
        "string_fence": json.dumps(fence),
    }
    assert download_result(stage, bodies[wrapper]).model_dump() == expected


@pytest.mark.parametrize("stage", RESULTS)
def test_ambiguous_artifact_blocks_are_rejected(stage):
    """Do not silently choose one of multiple candidate agent results."""
    block = f"```json\n{json.dumps(RESULTS[stage])}\n```"
    with pytest.raises(ValueError, match="exactly one JSON code block"):
        download_result(stage, f"First result:\n{block}\nAlternative result:\n{block}")


@pytest.mark.parametrize("stage", RESULTS)
def test_fenced_artifact_still_requires_strict_stage_schema(stage):
    """Formatting tolerance must not accept unexpected fields or bypass schema validation."""
    invalid = {**RESULTS[stage], "invented_field": "not in contract"}
    with pytest.raises(ValidationError):
        download_result(stage, f"Result:\n```json\n{json.dumps(invalid)}\n```\nDone.")


def test_intake_prefers_full_artifact_and_preserves_limitations():
    """Accept the observed Intake metadata instead of using the provider's incomplete summary."""
    artifact = {
        "incident_id": "ad37b805-68bf-4890-b520-9fc63c3361c0",
        "incident_type": "vehicle_collision",
        "summary": "Two vehicles collided at Market Street and 8th Street. One person is injured and conscious.",
        "reported_injuries": 1,
        "required_response_types": ["ambulance", "police"],
        "reasoning": "One reported injury requires medical evaluation; the collision requires traffic control.",
        "limitations": [
            "The report is an unverified resident account.",
            "The severity of the injury is not stated beyond the person being conscious.",
        ],
        "status": "complete",
    }
    downloads = []

    def download(request: httpx.Request) -> httpx.Response:
        """Return the full artifact while the inline result deliberately lacks required fields."""
        downloads.append(request.url.path)
        return httpx.Response(200, json=artifact)

    with httpx.Client(base_url="https://agent.creao.ai", transport=httpx.MockTransport(download)) as client:
        result = validate_completed_result("intake", {
            "text": json.dumps({
                "incident_id": artifact["incident_id"],
                "incident_type": "vehicle_collision",
                "reported_injuries": 1,
                "required_response_types": "ambulance, police",
                "status": "complete",
            }),
            "chatText": "All required inputs are present. Building and validating the artifact.",
            "artifacts": [{
                "type": "application/json",
                "title": "Incident ad37b805 — Kontrol Intake",
                "url": "https://agent.creao.ai/artifacts/incident.json",
            }],
        }, client)
    assert downloads == ["/artifacts/incident.json"]
    assert result.model_dump() == {**artifact, "caller_stated_location": None, "key_statements": []}


def test_intake_does_not_treat_failure_status_as_completed_output():
    """An optional completion marker cannot turn an agent-declared failure into a valid result."""
    with pytest.raises(ValidationError):
        download_result("intake", json.dumps({**RESULTS["intake"], "status": "failed"}))
