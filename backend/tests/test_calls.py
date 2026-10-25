"""Recorded-call security, durable transcription and review regression checks."""

from datetime import timedelta
from io import BytesIO

import httpx
import pytest
from pydantic import ValidationError
from sqlalchemy import func, select

from app import call_worker
from app.call_audio import inspect_audio
from app.call_services import ConfirmReview
from app.config import settings
from app.db import now
from app.models import AgentRun, Call, CoordinatorAction, Incident, Report, ResponsePlan
from app.response_schemas import IntakeResult
from app.sample_calls import SAMPLES
from app.transcription import LiveTranscription, MockTranscription, TranscriptResult, TranscriptionError
from call_helpers import COORDINATOR, submit_call

RESIDENT = {"Authorization": "Bearer demo-resident"}


def sample(client, key="collision"):
    """Create a queued call through the same authenticated sample endpoint as the UI."""
    response = client.post(f"/calls/sample/{key}", headers=COORDINATOR)
    assert response.status_code == 201, response.text
    return response.json()


def test_samples_decodable_and_mock_deterministic():
    """Every bundled recording plays and its mock transcript exactly matches its spoken script."""
    for item in SAMPLES.values():
        mime, duration = inspect_audio(item.audio_path)
        assert mime == "audio/wav" and 1 < duration < 300
        first = MockTranscription().transcribe(item.audio_path, mime, item.key)
        assert first.text == item.transcript
        assert first == MockTranscription().transcribe(item.audio_path, mime, item.key)
    with pytest.raises(TranscriptionError, match="bundled samples"):
        MockTranscription().transcribe(SAMPLES["fire"].audio_path, "audio/wav", None)


def test_review_is_atomic_unique_and_provenanced(system):
    """One reviewed recording creates one workflow and retains the original text and approximate pin."""
    client, factory = system
    queued = sample(client)
    assert "audio_key" not in queued and "claim_token" not in queued
    assert not client.get("/response-plans", headers=COORDINATOR).json()
    assert call_worker.process_one_call()
    call = client.get(f"/calls/{queued['id']}", headers=COORDINATOR).json()
    body = dict(
        latitude=37.777,
        longitude=-122.414,
        address="Exercise intersection",
        category="collision",
        transcript="SIMULATION: Vehicles collided; two people are reported injured.",
        version=call["version"],
    )
    path = f"/calls/{call['id']}/confirm-review"
    assert client.post(path, json={**body, "version": 1}, headers=COORDINATOR).status_code == 409
    confirmed = client.post(path, json=body, headers=COORDINATOR)
    assert confirmed.status_code == 200, confirmed.text
    assert confirmed.json()["original_transcript"] == SAMPLES["collision"].transcript
    assert confirmed.json()["reviewed_transcript"] == body["transcript"]
    assert confirmed.json()["caller_latitude"] != body["latitude"]
    assert client.post(path, json=body, headers=COORDINATOR).status_code == 409
    assert client.post(f"/calls/{call['id']}/retry-transcription", headers=COORDINATOR).status_code == 409
    with factory() as db:
        for model in [Report, Incident, ResponsePlan, AgentRun, CoordinatorAction]:
            assert db.scalar(select(func.count()).select_from(model)) == 1
        assert db.scalar(select(Report)).simulation is True
        assert db.scalar(select(CoordinatorAction)).action == "call_confirm_review"


@pytest.mark.parametrize(
    "method,path",
    [
        ("GET", "/calls"),
        ("GET", "/calls/samples"),
        ("POST", "/calls/sample/fire"),
        ("GET", "/calls/{id}"),
        ("GET", "/calls/{id}/audio"),
        ("DELETE", "/calls/{id}"),
        ("POST", "/calls/{id}/retry-transcription"),
        ("POST", "/calls/{id}/confirm-review"),
        ("POST", "/calls/{id}/locate"),
        ("POST", "/calls/{id}/reopen"),
        ("POST", "/calls"),
    ],
)
def test_call_permissions(system, method, path):
    """Every call endpoint rejects anonymous and non-dispatcher identities before data access."""
    client, _ = system
    call = sample(client)
    path = path.replace("{id}", call["id"])
    assert client.request(method, path).status_code == 401
    assert client.request(method, path, headers=RESIDENT).status_code == 403


def test_upload_validation_and_missing_caller_location(system, monkeypatch):
    """MIME spoofing, byte/duration limits and partial coordinates fail without orphan files."""
    client, _ = system
    audio = SAMPLES["collision"].audio_path.read_bytes()

    def upload(data=audio, mime="audio/wav", fields=None):
        """Send the real multipart contract without trusting the supplied filename."""
        return client.post(
            "/calls",
            headers=COORDINATOR,
            files={"audio": ("../../escape.wav", BytesIO(data), mime)},
            data=fields or {},
        )

    response = upload()
    assert response.status_code == 201, response.text
    assert response.json()["caller_latitude"] is None
    assert upload(b"not audio").status_code == 422
    assert upload(mime="text/html").status_code == 422
    assert upload(fields={"caller_latitude": "30"}).status_code == 422
    monkeypatch.setattr(settings, "call_max_audio_bytes", 10)
    assert upload().status_code == 413
    monkeypatch.setattr(settings, "call_max_audio_bytes", 20971520)
    monkeypatch.setattr(settings, "call_max_duration_seconds", 1)
    assert upload().status_code == 422
    from pathlib import Path

    assert len(list(Path(settings.call_audio_dir).iterdir())) == 1
    playback = client.get(f"/calls/{response.json()['id']}/audio", headers=COORDINATOR)
    assert playback.content == audio and playback.headers["cache-control"] == "no-store"
    assert call_worker.process_one_call()
    failed = client.get(f"/calls/{response.json()['id']}", headers=COORDINATOR).json()
    assert failed["status"] == "failed" and "bundled samples" in failed["transcription_error"]
    assert (
        client.post(f"/calls/{failed['id']}/retry-transcription", headers=COORDINATOR).json()["status"]
        == "queued"
    )


def test_failed_ingestion_rolls_back_confirmation(system, monkeypatch):
    """A failure after report creation cannot leave an orphan workflow or partial review."""
    client, factory = system
    queued = sample(client)
    call_worker.process_one_call()
    call = client.get(f"/calls/{queued['id']}", headers=COORDINATOR).json()
    from app import call_services

    original = call_services.ingest_report

    def broken(*args, **kwargs):
        """Raise after constructing the workflow to exercise request-session rollback."""
        original(*args, **kwargs)
        raise RuntimeError("test transaction failure")

    monkeypatch.setattr(call_services, "ingest_report", broken)
    with pytest.raises(RuntimeError):
        client.post(
            f"/calls/{call['id']}/confirm-review",
            headers=COORDINATOR,
            json={
                "latitude": 37.7,
                "longitude": -122.4,
                "address": "Exercise block",
                "category": "fire",
                "transcript": call["original_transcript"],
                "version": call["version"],
            },
        )
    with factory() as db:
        assert db.get(Call, call["id"]).status == "awaiting_review"
        assert not db.scalar(select(Report)) and not db.scalar(select(ResponsePlan))


def test_intake_uses_reviewed_text_and_carries_uncertainty(system):
    """Agents see confirmed coordinates and reviewed text, with limitations preserved into final review."""
    client, factory = system
    result = submit_call(
        client, {"description": "SIMULATION: Building fire. Patient count is unknown.", "category": "fire"}
    )
    from app import worker

    for _ in range(4):
        assert worker.process_one()
    plan = client.get(f"/response-plans/{result.json()['plan_id']}", headers=COORDINATOR).json()
    intake = next(run for run in plan["runs"] if run["stage"] == "intake")
    payload = intake["input"]["agent_input"]
    assert payload["transcript"].endswith("Patient count is unknown.")
    assert set(payload) == {"incident_id", "transcript", "confirmed_location", "call_received_at", "category"}
    assert payload["confirmed_location"]["latitude"] == 37.777
    assert intake["output"]["reported_injuries"] is None
    assert set(intake["output"]["limitations"]).issubset(plan["constraints"])
    assert plan["requirements"]["patient_count_verification"] == "unconfirmed_agent_estimate"
    assert plan["call"]["original_transcript"] != plan["call"]["reviewed_transcript"]
    for path in ["/incidents", "/reports", "/response-plans", "/agents"]:
        assert client.get(path, headers=COORDINATOR).json()


def test_strict_transcript_and_intake_bounds():
    """Reject unsupported output fields, excessive quotes and overlong text without truncation."""
    assert TranscriptResult(text="A visible\x00 transcript.").text == "A visible transcript."
    with pytest.raises(ValidationError):
        TranscriptResult(text="x" * 4001)
    valid = dict(
        incident_id="source",
        incident_type="fire",
        summary="Exercise summary",
        reasoning="Exercise only",
        required_response_types=["fire_rescue"],
    )
    for extra in [
        {"official_status": "verified"},
        {"key_statements": ["x"] * 11},
        {"key_statements": ["x" * 501]},
        {"reported_injuries": 101},
    ]:
        with pytest.raises(ValidationError):
            IntakeResult(**valid, **extra)
    with pytest.raises(ValidationError):
        ConfirmReview(
            latitude=0, longitude=0, address="Exercise", transcript="x" * 4001, category="fire", version=1
        )


@pytest.mark.parametrize("failure", [None, "timeout", "http", "oversized", "bad_text", "bad_json"])
def test_live_transcription_documented_request(monkeypatch, failure):
    """Exercise the documented multipart contract and bounded sanitized failure paths without keys."""

    def handler(request):
        """Inspect actual encoded multipart bytes and return controlled provider responses."""
        assert request.url.path == "/v1/audio/transcriptions"
        assert request.headers["authorization"] == "Bearer test-key"
        body = request.read()
        assert b'name="file"' in body and b'name="model"' in body and b'name="response_format"' in body
        assert b"json" in body and b"RIFF" in body
        if failure == "timeout":
            raise httpx.ReadTimeout("private provider error")
        if failure == "http":
            return httpx.Response(500, text="private provider error")
        if failure == "oversized":
            return httpx.Response(200, content=b"x" * 70000)
        if failure == "bad_text":
            return httpx.Response(200, json={"text": "x" * 4001})
        if failure == "bad_json":
            return httpx.Response(200, content=b"not json")
        return httpx.Response(
            200, json={"text": "This is a simulated recording.", "usage": {"type": "duration"}}
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    monkeypatch.setattr(settings, "transcription_api_key", "test-key")
    if failure:
        with pytest.raises(TranscriptionError) as error:
            LiveTranscription().transcribe(SAMPLES["collision"].audio_path, "audio/wav", None)
        assert "private provider error" not in str(error.value) and "test-key" not in str(error.value)
    else:
        assert (
            LiveTranscription()
            .transcribe(SAMPLES["collision"].audio_path, "audio/wav", None)
            .text.startswith("This is")
        )


def test_expired_claim_requires_manual_retry(system):
    """An expired attempt retains failure provenance and retry cannot reuse its claim token."""
    client, factory = system
    call = sample(client)
    with factory() as db:
        row = db.get(Call, call["id"])
        row.status, row.claim_token, row.attempts = "transcribing", "old-token", 1
        row.lease_expires_at = now() - timedelta(seconds=1)
        db.commit()
    assert not call_worker.process_one_call()
    failed = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert failed["status"] == "failed"
    assert client.post(f"/calls/{call['id']}/retry-transcription", headers=COORDINATOR).status_code == 200
    assert call_worker.process_one_call()
    assert client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()["attempts"] == 2


def test_disabled_live_simulation_rejects_before_queueing(system, monkeypatch):
    """Disabled exercise execution must create neither paid jobs nor stranded recordings."""
    client, factory = system
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "live_simulation_enabled", False)
    assert client.post("/calls/sample/collision", headers=COORDINATOR).status_code == 409
    with factory() as db:
        assert not db.scalar(select(Call)) and not db.scalar(select(AgentRun))


def test_provider_switch_preserves_exercise_history(system, monkeypatch):
    """Changing execution mode cannot hide confirmed calls, plans, assignments or their audit history."""
    client, _ = system
    confirmed = submit_call(client).json()
    from app import worker

    for _ in range(4):
        worker.process_one()
    plan = client.get(f"/response-plans/{confirmed['plan_id']}", headers=COORDINATOR).json()
    approved = client.post(
        f"/response-plans/{plan['id']}/decision",
        headers=COORDINATOR,
        json={"action": "approve", "version": plan["version"], "note": "Reviewed fictional call"},
    )
    assert approved.status_code == 200
    assert client.get("/communications", headers=COORDINATOR).status_code == 404
    monkeypatch.setattr(settings, "creao_mode", "live")
    monkeypatch.setattr(settings, "live_simulation_enabled", False)
    for path in [
        "/calls",
        "/reports",
        "/incidents",
        "/response-plans",
        "/dispatches",
        "/agents",
        "/activity",
    ]:
        assert client.get(path, headers=COORDINATOR).json()
    assert client.get(f"/response-plans/{plan['id']}", headers=COORDINATOR).json()["assignments"]
    assert client.get(f"/incidents/{confirmed['incident_id']}", headers=COORDINATOR).status_code == 200
    assert client.get(f"/reports/{confirmed['report_id']}", headers=COORDINATOR).status_code == 200
