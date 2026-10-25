"""Automatic call-location inference and category-only intake boundaries."""

import httpx
import pytest
from sqlalchemy import select

from app import call_worker
from app.call_location import detect_location, geocode_address
from app.config import settings
from app.models import AgentRun, Call, CoordinatorAction, Report
from app.sample_calls import SAMPLES
from app.transcription import TranscriptResult
from call_helpers import COORDINATOR


@pytest.mark.parametrize(
    "key,address,latitude",
    [
        ("collision", "Market & 8th exercise area", 37.777),
        ("cardiac", "Mission exercise block", 37.758),
        ("fire", "Richmond exercise block", 37.780),
    ],
)
def test_sample_locations_come_from_spoken_text(key, address, latitude):
    """Exercise landmarks resolve without network access or caller-device coordinates."""
    result = detect_location(SAMPLES[key].transcript)
    assert result.status == "resolved" and result.address == address
    assert result.latitude == latitude and result.source == "exercise_gazetteer"
    assert result.latitude != SAMPLES[key].latitude
    assert result.evidence.lower() in SAMPLES[key].transcript.lower()


def test_missing_and_conflicting_locations_stay_unknown():
    """An unknown landmark or multiple places must not become a made-up incident pin."""
    for transcript in [
        "Someone needs help; I don't know where.",
        "Mission exercise block or Richmond exercise block.",
        "Market and Eighth. Also someone at 123 Main Street.",
    ]:
        result = detect_location(transcript)
        assert result.status == "unavailable" and result.latitude is None


def test_category_only_start_uses_server_location(system):
    """The dispatcher selects call type while server-owned transcript and location create the workflow."""
    client, factory = system
    queued = client.post("/calls/sample/collision", headers=COORDINATOR).json()
    assert call_worker.process_one_call()
    call = client.get(f"/calls/{queued['id']}", headers=COORDINATOR).json()
    path = f"/calls/{call['id']}/start"
    payload = {"category": "collision", "version": call["version"]}
    assert client.post(path, headers=COORDINATOR, json={**payload, "latitude": 0}).status_code == 422
    assert client.post(path, headers=COORDINATOR, json={**payload, "version": 1}).status_code == 409
    for headers, status in [({}, 401), ({"Authorization": "Bearer demo-resident"}, 403)]:
        assert client.post(path, headers=headers, json=payload).status_code == status
    response = client.post(path, headers=COORDINATOR, json=payload)
    assert response.status_code == 200, response.text
    assert response.json()["confirmed_address"] == "Market & 8th exercise area"
    assert response.json()["confirmed_latitude"] == 37.777
    assert response.json()["reviewed_transcript"] == SAMPLES["collision"].transcript
    assert client.post(path, headers=COORDINATOR, json=payload).status_code == 409
    with factory() as db:
        assert len(list(db.scalars(select(Report)))) == 1
        assert "automatic_from_transcript" in db.scalar(select(CoordinatorAction)).details
    from app import worker

    for _ in range(4):
        assert worker.process_one()
    plan = client.get(f"/response-plans/{response.json()['plan_id']}", headers=COORDINATOR).json()
    assert any("not human-verified" in constraint for constraint in plan["constraints"])


def test_unresolved_location_cannot_start_agents(system, monkeypatch):
    """An unresolved transcript remains visible but creates no report or agent jobs."""
    client, factory = system

    class UnknownLocation:
        """Return a valid transcript with no geographic evidence."""

        def transcribe(self, *args):
            """Supply missing-location text rather than relying on the sample key."""
            return TranscriptResult(
                text="This is a simulation. Someone is injured. I do not know the address."
            )

    monkeypatch.setattr(call_worker, "get_transcription_adapter", UnknownLocation)
    call = client.post("/calls/sample/fire", headers=COORDINATOR).json()
    assert call_worker.process_one_call()
    call = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert call["detected_location"]["status"] == "unavailable"
    assert (
        client.post(
            f"/calls/{call['id']}/start",
            headers=COORDINATOR,
            json={"category": "fire", "version": call["version"]},
        ).status_code
        == 409
    )
    with factory() as db:
        assert not db.scalar(select(Report)) and not db.scalar(select(AgentRun))


def test_existing_transcripts_enriched_without_paid_retranscription(system, monkeypatch):
    """Calls created before the migration gain location metadata without replacing their original text."""
    client, factory = system
    call = client.post("/calls/sample/fire", headers=COORDINATOR).json()
    with factory() as db:
        row = db.get(Call, call["id"])
        row.status, row.original_transcript, row.attempts = "awaiting_review", SAMPLES["fire"].transcript, 1
        db.commit()

    def forbidden():
        """Fail if migration enrichment attempts another provider invocation."""
        raise AssertionError("No retranscription expected")

    monkeypatch.setattr(call_worker, "get_transcription_adapter", forbidden)
    assert call_worker.process_one_call()
    current = client.get(f"/calls/{call['id']}", headers=COORDINATOR).json()
    assert current["original_transcript"] == SAMPLES["fire"].transcript and current["attempts"] == 1
    assert current["detected_location"]["status"] == "resolved"


@pytest.mark.parametrize(
    "mode,expected",
    [
        ("match", "resolved"),
        ("ambiguous", "unavailable"),
        ("mismatch", "unavailable"),
        ("outside", "unavailable"),
        ("malformed", "unavailable"),
        ("timeout", "unavailable"),
        ("oversized", "unavailable"),
    ],
)
def test_geocoder_contract_and_failures(monkeypatch, mode, expected):
    """Only one matching SF address is accepted; provider failures cannot fabricate coordinates."""

    def handler(request):
        """Inspect the documented Photon query and return controlled GeoJSON."""
        assert request.url.path == "/api"
        assert request.headers["user-agent"] == "Kontrol-Simulation/1.0"
        assert request.url.params["q"] == "123 Main Street"
        assert request.url.params["limit"] == "5" and "bbox" in request.url.params
        if mode == "timeout":
            raise httpx.ReadTimeout("provider failure")
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * 70000)
        if mode == "malformed":
            return httpx.Response(200, json={"unexpected": "shape"})
        feature = {
            "geometry": {"type": "Point", "coordinates": [-122.41, 37.77]},
            "properties": {"housenumber": "123", "street": "Main St"},
        }
        if mode == "mismatch":
            feature["properties"]["housenumber"] = "999"
        if mode == "outside":
            feature["geometry"]["coordinates"] = [0, 0]
        features = [feature]
        if mode == "ambiguous":
            features.append({**feature, "geometry": {"type": "Point", "coordinates": [-122.42, 37.76]}})
        return httpx.Response(200, json={"features": features})

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    assert (
        detect_location("SIMULATION. The incident is at 123 Main Street. Two people are injured.").status
        == expected
    )
    monkeypatch.setattr(settings, "call_geocoding_url", "")
    assert geocode_address("123 Main Street").status == "unavailable"
