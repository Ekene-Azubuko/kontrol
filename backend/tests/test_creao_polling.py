"""Exercise completion polling and rate limits without network calls or real sleeps."""

import httpx
import pytest
from pydantic import ValidationError

from app import creao
from app.config import Settings, settings


@pytest.mark.parametrize("interval", [2, 7])
def test_poll_interval_and_provider_backoff(monkeypatch, interval):
    """Use the configured completion interval while honoring a longer provider rate limit."""
    output = {
        "incident_id": "test-report",
        "incident_type": "vehicle_collision",
        "summary": "A fictional collision was reported.",
        "reported_injuries": None,
        "required_response_types": ["ambulance"],
        "reasoning": "The caller reports an injury.",
        "limitations": ["Patient count is unknown."],
    }
    requests: list[httpx.Request] = []
    sleeps: list[float] = []

    def handler(request: httpx.Request) -> httpx.Response:
        """Start once, observe pending work, respect throttling, then validate completion."""
        requests.append(request)
        if len(requests) == 1:
            assert request.method == "POST"
            return httpx.Response(202, json={"id": "remote-run"})
        assert request.method == "GET"
        assert request.url.path == "/api/v1/runs/remote-run"
        if len(requests) == 2:
            return httpx.Response(200, json={"status": "running"})
        if len(requests) == 3:
            return httpx.Response(429, headers={"Retry-After": "9"})
        return httpx.Response(200, json={"status": "completed", "result": {"output": output}})

    original_client = httpx.Client
    monkeypatch.setattr(httpx, "Client", lambda **kwargs: original_client(
        transport=httpx.MockTransport(handler), **kwargs,
    ))
    monkeypatch.setattr(settings, "creao_base_url", "https://creao.test")
    monkeypatch.setattr(settings, "creao_api_key", "test-key")
    monkeypatch.setattr(settings, "creao_api_version", "v1")
    monkeypatch.setattr(settings, "creao_invoke_path", "")
    monkeypatch.setattr(settings, "creao_poll_path", "")
    monkeypatch.setattr(settings, "creao_intake_agent_id", "test-intake")
    monkeypatch.setattr(settings, "creao_poll_seconds", interval)
    monkeypatch.setattr(settings, "creao_timeout", 60)
    monkeypatch.setattr(creao.time, "monotonic", lambda: sum(sleeps))
    monkeypatch.setattr(creao.time, "sleep", sleeps.append)

    result = creao.LiveAdapter().invoke("intake", {
        "job_id": "test-job", "agent_input": {"incident_id": "test-report"},
    })

    assert result.incident_id == "test-report"
    assert result.reported_injuries is None
    assert result.limitations == output["limitations"]
    assert len(requests) == 4
    assert sleeps == [interval, 9]


@pytest.mark.parametrize("interval", [-1, 0, 0.5, float("nan"), float("inf")])
def test_invalid_poll_interval_is_rejected(interval):
    """Reject values that cannot provide a bounded, rate-conscious completion cadence."""
    with pytest.raises(ValidationError):
        Settings(_env_file=None, creao_poll_seconds=interval)
