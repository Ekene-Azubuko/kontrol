"""Regression coverage for complete JSON embedded in CREAO progress text."""

import json

import pytest
from pydantic import ValidationError

from app.agent_errors import agent_error_message
from app.creao import json_text, validate_result
from test_creao_artifacts import RESULTS


@pytest.mark.parametrize("stage", RESULTS)
def test_full_chat_result_after_incomplete_provider_summary(stage):
    """Use the valid chat result when CREAO's text field contains only a summary envelope."""
    expected = {**RESULTS[stage], "reasoning": 'Reviewed literal braces {scene} and quoted text "unknown".'}
    expected["limitations"] = ["Count remains unknown; do not infer zero."]
    result = validate_result(stage, {
        "text": json.dumps({"incident_id": "incident-1", "status": "success", "options_found": 0}),
        "chatText": "Inputs validated; carry missing counts as unknown. Preparing result."
        + json.dumps(expected) + "\nFinished.",
    })
    assert result.model_dump() == expected


@pytest.mark.parametrize("suffix", ["another {}", "another []", "partial {", "}"])
def test_multiple_or_unbalanced_documents_are_rejected(suffix):
    """Never select the first valid result when trailing delimiters make the document ambiguous."""
    with pytest.raises(ValueError, match="exactly one complete"):
        json_text(f"Result: {json.dumps(RESULTS['hospital'])} {suffix}")


@pytest.mark.parametrize("prefix", ["{invalid:", "[invalid,", '{"outer":', '['])
def test_malformed_outer_document_is_not_salvaged(prefix):
    """Do not scan past invalid syntax to accept a nested fragment as the stage result."""
    with pytest.raises(ValueError):
        validate_result("hospital", {"chatText": f"Result: {prefix}{json.dumps(RESULTS['hospital'])}"})


def test_prose_does_not_relax_schema_or_unknown_values():
    """Formatting support still rejects unexpected fields and preserves unknown patient counts."""
    with pytest.raises(ValidationError):
        validate_result("hospital", {"chatText": "Result: " + json.dumps({**RESULTS["hospital"], "secret": "value"})})
    expected = {**RESULTS["intake"], "reported_injuries": None}
    result = validate_result("intake", {"chatText": "Result: " + json.dumps(expected)})
    assert result.reported_injuries is None


def test_questions_and_wrappers_are_not_hospital_results():
    """Do not mistake the previous interactive injury-count question for a completed stage."""
    with pytest.raises(ValueError):
        validate_result("hospital", {"text": json.dumps({"response": "Please tell me the injury count."})})


def test_schema_error_is_actionable_without_raw_inputs():
    """List missing contract fields without echoing untrusted text or unknown field names."""
    secret = "private-provider-value"
    try:
        validate_result("hospital", {"output": {secret: secret, "incident_id": "incident-1"}})
    except ValidationError as exc:
        message = agent_error_message("hospital", exc)
    else:
        pytest.fail("Invalid provider output was accepted")
    assert "missing hospitals, reasoning, recommended_hospitals" in message
    assert "unexpected fields" in message and secret not in message


def test_nested_schema_error_names_only_the_contract_field():
    """Do not echo invalid nested values or provider exception text into the interface."""
    try:
        validate_result("hospital", {"output": {**RESULTS["hospital"], "hospitals": ["private-value"]}})
    except ValidationError as exc:
        message = agent_error_message("hospital", exc)
    else:
        pytest.fail("Invalid hospital entries were accepted")
    assert "invalid hospitals" in message and "private-value" not in message
    assert "private-value" not in agent_error_message("hospital", RuntimeError("private-value"))
