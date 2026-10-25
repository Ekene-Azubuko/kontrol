"""Readable agent failures without disclosing provider values, credentials or transcript contents."""

from pydantic import ValidationError

from .response_schemas import stage_schema


def agent_error_message(stage: str, exc: Exception) -> str:
    """Expose schema-owned field names while keeping raw invalid inputs out of user-facing errors."""
    if not isinstance(exc, ValidationError):
        return f"{type(exc).__name__}: output validation or execution failed; inspect worker logs"
    fields = stage_schema(stage).model_fields
    missing, invalid = set(), set()
    unexpected = False
    for error in exc.errors(include_input=False, include_url=False):
        location = error["loc"]
        unexpected |= error["type"] == "extra_forbidden"
        if location and location[0] in fields:
            target = missing if error["type"] == "missing" and len(location) == 1 else invalid
            target.add(location[0])
    details = []
    if missing:
        details.append("missing " + ", ".join(sorted(missing)))
    if invalid:
        details.append("invalid " + ", ".join(sorted(invalid)))
    if unexpected:
        details.append("unexpected fields")
    reason = "; ".join(details) or "invalid JSON or field values"
    return f"Agent output failed schema validation ({reason}). Check the published {stage.title()} result contract."
