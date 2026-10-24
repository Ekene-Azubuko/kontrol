"""Isolated CREAO contract; no default undocumented endpoint assumptions."""

import json
import re
import time
from urllib.parse import urlparse

import httpx

from .config import settings
from pydantic import BaseModel
from .response_schemas import stage_schema
from . import mock_response


class MockAdapter:
    """Run four deterministic, supplied-data response agents without credentials."""

    def invoke(self, stage: str, payload: dict) -> BaseModel:
        """Match the live stage contract with an observable, configurable demo duration."""
        stage_schema(stage)
        time.sleep(max(0, settings.mock_agent_seconds))
        return getattr(mock_response, stage)(payload)


class LiveAdapter:
    """Implement CREAO's documented v1 API Trigger with bounded polling and retries."""

    def invoke(self, stage: str, payload: dict) -> BaseModel:
        """Use a stable job idempotency key and validate the final JSON assessment."""
        agent_id = getattr(settings, f"creao_{stage}_agent_id")
        if not all([settings.creao_base_url, settings.creao_api_key, agent_id]):
            raise RuntimeError("Live CREAO credentials and agent IDs are required; see backend/CREAO.md")
        if settings.creao_api_version != "v1":
            raise RuntimeError("Only CREAO's documented and observed v1 request envelope is enabled")
        if not settings.creao_base_url.startswith("https://"):
            raise RuntimeError("Live CREAO requires HTTPS")
        invoke_path = settings.creao_invoke_path or "/api/{version}/runs"
        poll_path = settings.creao_poll_path or "/api/{version}/runs/{run_id}"
        path_values = {"version": settings.creao_api_version, "agent_id": agent_id}
        headers = {"Authorization": f"Bearer {settings.creao_api_key}"}
        deadline = time.monotonic() + settings.creao_timeout
        context = payload["agent_input"]
        request_body = {
            "appId": agent_id,
            "inputs": {settings.creao_input_field: json.dumps(context)},
            "idempotencyKey": f"kontrol-{payload['job_id']}-{stage}",
        }
        with httpx.Client(base_url=settings.creao_base_url, headers=headers, timeout=15) as client:
            run_id = payload.get("remote_id")
            if not run_id:
                for attempt in range(5):
                    try:
                        response = client.post(invoke_path.format(**path_values), json=request_body)
                        response.raise_for_status()
                        run_id = response.json()["id"]
                        break
                    except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                        # Retrying this POST is safe because CREAO documents idempotencyKey.
                        if isinstance(exc, httpx.HTTPStatusError):
                            status = exc.response.status_code
                            if status < 500 and status != 429:
                                raise
                            delay = retry_delay(exc.response, attempt)
                        else:
                            delay = min(30, 2 ** attempt)
                        if attempt == 4 or time.monotonic() + delay >= deadline:
                            raise
                        time.sleep(delay)
            if not run_id:
                raise RuntimeError("CREAO did not return a run ID")
            self.remote_id = run_id
            failures = 0
            while time.monotonic() < deadline:
                try:
                    result = client.get(poll_path.format(**path_values, run_id=run_id))
                    result.raise_for_status()
                    data = result.json()
                    failures = 0
                except (httpx.TransportError, httpx.HTTPStatusError) as exc:
                    if isinstance(exc, httpx.HTTPStatusError) and exc.response.status_code == 429:
                        delay = retry_delay(exc.response, failures)
                        if time.monotonic() + delay >= deadline:
                            raise TimeoutError("CREAO polling remained rate limited until timeout") from exc
                        failures += 1
                        time.sleep(delay)
                        continue
                    failures += 1
                    if failures >= 3:
                        raise
                    time.sleep(failures)
                    continue
                if data["status"] == "completed":
                    self.raw_response = data
                    return validate_completed_result(stage, data["result"], client)
                if data["status"] in {"failed", "cancelled"}:
                    raise RuntimeError("CREAO run failed; inspect the provider execution log")
                time.sleep(max(1, settings.creao_poll_seconds))
        raise TimeoutError("CREAO run exceeded configured timeout")


def validate_result(stage: str, result: dict) -> BaseModel:
    """Parse documented structured or textual CREAO result fields against the stage contract."""
    first_error: Exception | None = None
    for field in ("output", "data", "text", "chatText"):
        output = result.get(field)
        if isinstance(output, dict):
            try:
                return stage_schema(stage).model_validate(output)
            except ValueError as exc:
                first_error = first_error or exc
                continue
        if not isinstance(output, str) or not output.strip():
            continue
        try:
            return stage_schema(stage).model_validate_json(json_text(output))
        except ValueError as exc:
            first_error = first_error or exc
    if first_error:
        raise first_error
    raise ValueError("CREAO completed without a non-empty text or chatText result")


def retry_delay(response: httpx.Response, attempt: int) -> float:
    """Honor a numeric Retry-After value or use bounded exponential backoff."""
    value = response.headers.get("Retry-After")
    if value:
        try:
            return min(60, max(1, float(value)))
        except ValueError:
            pass
    return min(30, 5 * (2 ** min(attempt, 3)))


def validate_completed_result(stage: str, result: dict, client: httpx.Client) -> BaseModel:
    """Prefer the canonical JSON artifact, then fall back to inline CREAO result fields."""
    first_error: Exception | None = None
    base = urlparse(str(client.base_url))
    for artifact in result.get("artifacts", []):
        media_type = str(artifact.get("type", "")).lower()
        title = str(artifact.get("title", "")).lower()
        url = artifact.get("url")
        if not isinstance(url, str) or not (media_type == "application/json" or title.endswith(".json")):
            continue
        parsed = urlparse(url)
        if parsed.scheme != "https" or parsed.netloc != base.netloc:
            first_error = first_error or ValueError("CREAO artifact URL must use the configured HTTPS origin")
            continue
        try:
            response = client.get(url)
            if response.is_redirect:
                redirect_url = response.headers.get("location", "")
                redirect = urlparse(redirect_url)
                if redirect.scheme != "https" or not redirect.netloc.endswith(".amazonaws.com"):
                    raise ValueError("CREAO artifact redirect must use HTTPS AWS object storage")
                # Use a clean client so the CREAO bearer token is never forwarded to object storage.
                with httpx.Client(timeout=15) as artifact_client:
                    response = artifact_client.get(redirect_url)
            response.raise_for_status()
            try:
                content = response.json()
            except json.JSONDecodeError:
                # CREAO may label a Markdown document application/json; validate its sole JSON block.
                content = response.text
            if isinstance(content, str):
                return stage_schema(stage).model_validate_json(json_text(content))
            return stage_schema(stage).model_validate(content)
        except (httpx.HTTPError, json.JSONDecodeError, ValueError) as exc:
            first_error = first_error or exc
    try:
        return validate_result(stage, result)
    except ValueError:
        if first_error:
            raise first_error
        raise


def json_text(value: str) -> str:
    """Accept bare JSON or one unambiguous fenced result, including CREAO's surrounding prose."""
    stripped = value.strip()
    try:
        json.loads(stripped)
        return stripped
    except json.JSONDecodeError:
        pass
    if "```" not in stripped:
        return stripped
    # Never choose between multiple documents; an agent must provide one canonical result.
    if stripped.count("```") != 2:
        raise ValueError("CREAO text must contain exactly one JSON code block")
    match = re.search(r"```(?:json)?\s*([\s\S]*?)\s*```", stripped, flags=re.IGNORECASE)
    return match.group(1).strip() if match else stripped


def get_adapter() -> MockAdapter | LiveAdapter:
    """Select the same application-level interface for mock and live execution."""
    if settings.creao_mode not in {"mock", "live"}:
        raise ValueError("CREAO_MODE must be mock or live")
    return MockAdapter() if settings.creao_mode == "mock" else LiveAdapter()
