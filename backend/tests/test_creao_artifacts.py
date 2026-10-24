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
@pytest.mark.parametrize("wrapper", ["bare", "fence", "prose", "string_json", "string_fence"])
def test_artifact_formats_validate_for_every_stage(stage, wrapper):
    """Accept the observed prose-wrapped artifact and existing supported JSON encodings."""
    expected = RESULTS[stage]
    encoded = json.dumps(expected)
    fence = f"```json\n{encoded}\n```"
    bodies = {
        "bare": encoded,
        "fence": fence,
        "prose": f"` (also saved at `files/result.json`).\n\n{fence}\n\nUnverified report.",
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
