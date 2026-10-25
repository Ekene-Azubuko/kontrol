"""Regression coverage for spoken intersections and exact shared GIS street nodes."""

import httpx
import pytest

from app.call_location import detect_location
from app import street_directory
from app.street_intersections import spoken_intersections

TRANSCRIPT = (
    "911, what's your emergency? Help, I think there's been a car accident. "
    "Uh, what's your address, ma'am? Um, I think it was the intersection of Greenwich and Van Ness. "
    "And how many cars were involved in the accident? Um, it was a car and a bicycle. "
    "Do we have anyone hurt in the incident? I think so. The guy on the bike is currently unconscious. "
    "Okay, I will reach out to the first responders and get them to your address. Thank you, hurry, he's dying."
)
VANESS_TRANSCRIPT = (
    "Hi, 911, what's your emergency? I just got into an accident and I think I broke my leg. "
    "Oh, that's bad. What is your location? um, Vaness and Union. OK, thank you. Um, we'll be there soon."
)


@pytest.fixture(autouse=True)
def clear_directory_cache():
    """Prevent mocked city street directories from leaking between test cases."""
    loader = street_directory.load_street_directory
    loader.cache_clear()
    yield
    loader.cache_clear()


def street_rows(mode="match"):
    """Return a small city-data-shaped response with a real junction and unrelated street nodes."""
    rows = [
        {
            "cnn": "26692000.0",
            "st_name": "GREENWICH",
            "st_type": "ST",
            "the_geom": {"type": "Point", "coordinates": [-122.424358668, 37.800415027]},
        },
        {
            "cnn": "26692000.0",
            "st_name": "VAN NESS",
            "st_type": "AVE",
            "the_geom": {"type": "Point", "coordinates": [-122.424358668, 37.800415027]},
        },
        {
            "cnn": "other",
            "st_name": "VAN NESS",
            "st_type": "AVE",
            "the_geom": {"type": "Point", "coordinates": [-122.42, 37.79]},
        },
    ]
    if mode == "no_shared_node":
        rows[1]["cnn"] = "separate"
    if mode == "ambiguous":
        rows += [
            {**row, "cnn": "second", "the_geom": {"type": "Point", "coordinates": [-122.425, 37.801]}}
            for row in rows[:2]
        ]
    if mode == "invalid_coordinates":
        rows[0]["the_geom"]["coordinates"] = [0, 0]
    if mode == "malformed":
        return [{"unexpected": "shape"}]
    return rows


def mock_city_service(monkeypatch, mode="match"):
    """Serve deterministic public GIS rows and inspect the exact projected query contract."""

    def handler(request):
        """Keep the entire private transcript out of the public street-name lookup."""
        assert request.url.host == "data.sf.gov"
        if request.url.params["$select"] == "st_name,st_type":
            assert request.url.params["$group"] == "st_name,st_type"
            return httpx.Response(
                200,
                json=[
                    {"st_name": "GREENWICH", "st_type": "ST"},
                    {"st_name": "VAN NESS", "st_type": "AVE"},
                ],
            )
        assert request.url.params["$select"] == "cnn,st_name,st_type,the_geom"
        assert "GREENWICH" in request.url.params["$where"] and "VAN NESS" in request.url.params["$where"]
        assert "unconscious" not in str(request.url)
        if mode == "timeout":
            raise httpx.ReadTimeout("private upstream detail")
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * 270000)
        return httpx.Response(200, json=street_rows(mode))

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )


@pytest.mark.parametrize(
    "phrase",
    [
        TRANSCRIPT,
        "At Greenwich and Van Ness.",
        "Near Greenwich St and Van Ness Ave, someone is injured.",
        "The corner of Greenwich Street & Van Ness Avenue.",
        "Greenwich / Van Ness.",
        "Greenwich and Van Ness.",
        "At Van Ness and Greenwich.",
        "What's your location? Um, Greenwich and Van Ness. Someone needs help.",
        "Where are you? Caller: uh, Greenwich and Van Ness. Please hurry.",
        "What is your address, ma'am? Well, Greenwich and Van Ness.",
        "We're on Greenwich and Van Ness right now.",
    ],
)
def test_spoken_intersection_variants_resolve(monkeypatch, phrase):
    """Omitted suffixes, multiword streets, connectors and reversed order all identify the crossing."""
    mock_city_service(monkeypatch)
    result = detect_location(phrase)
    assert result.status == "resolved" and result.source == "sf_intersections"
    assert result.latitude == 37.800415027 and result.longitude == -122.424358668
    assert "Greenwich" in result.address and "Van Ness" in result.address
    assert result.reference == "https://data.sf.gov/d/gmfx-8h6i"


@pytest.mark.parametrize(
    "mode", ["no_shared_node", "ambiguous", "invalid_coordinates", "malformed", "timeout", "oversized"]
)
def test_intersection_failures_remain_unavailable(monkeypatch, mode):
    """Separate street centers, ambiguous junctions and provider failures never produce a guessed pin."""
    mock_city_service(monkeypatch, mode)
    result = detect_location(TRANSCRIPT)
    assert result.status == "unavailable" and result.latitude is None
    assert result.evidence == "Greenwich & Van Ness"
    assert "private upstream detail" not in result.reason


def test_wrong_explicit_street_type_does_not_match(monkeypatch):
    """A named avenue must not be silently substituted for a different explicitly named street type."""
    mock_city_service(monkeypatch)
    assert detect_location("At Greenwich Road and Van Ness Avenue.").status == "unavailable"


def test_multiple_places_and_repeated_intersections(monkeypatch):
    """Repeated references are deduplicated while different incident locations stay ambiguous."""
    mock_city_service(monkeypatch)
    assert detect_location("At Greenwich and Van Ness. At Van Ness and Greenwich.").status == "resolved"
    result = detect_location("At Greenwich and Van Ness. At Mission and Sixth.")
    assert result.status == "unavailable" and "multiple locations" in result.reason
    assert detect_location("At Greenwich and Van Ness. Also at 123 Main Street.").status == "unavailable"


def test_street_name_literals_and_numbered_street_normalization():
    """Preserve meaningful street-name words and normalize city ordinal labels without SQL fragments."""
    pair = spoken_intersections("At 5th Street and O'Farrell Street.", [])[0]
    assert pair.first.name == "05TH" and pair.second.name == "O'FARRELL"
    assert pair.first.street_type == "ST"


def mock_union_service(monkeypatch):
    """Track city lookups for the typo regression using a deterministic shared-node fixture."""
    queries = []

    def handler(request):
        """Return official-shaped names and a shared node without ever receiving private call dialogue."""
        queries.append(dict(request.url.params))
        assert "broke" not in str(request.url) and "Vaness" not in str(request.url)
        if request.url.params["$select"] == "st_name,st_type":
            return httpx.Response(
                200,
                json=[
                    {"st_name": "VAN NESS", "st_type": "AVE"},
                    {"st_name": "UNION", "st_type": "ST"},
                    {"st_name": "AVENUE B"},
                ],
            )
        assert request.url.params["$where"] == "st_name in ('VAN NESS','UNION')"
        return httpx.Response(
            200,
            json=[{**row, "st_name": name} for row, name in zip(street_rows()[:2], ["VAN NESS", "UNION"])],
        )

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    return queries


@pytest.mark.parametrize("phrase", [VANESS_TRANSCRIPT, "Um, Vaness and Union.", "At Vanness and Union."])
def test_misspelled_location_answer_preserves_evidence(monkeypatch, phrase):
    """A short conversational answer can normalize one typo without changing the original spoken evidence."""
    queries = mock_union_service(monkeypatch)
    result = detect_location(phrase)
    assert result.status == "resolved" and result.address == "Van Ness & Union"
    assert result.evidence == ("Vanness & Union" if "Vanness" in phrase else "Vaness & Union")
    assert result.source == "sf_intersections" and "not human-verified" in result.reason
    assert len(queries) == 2
    assert detect_location(phrase).status == "resolved"
    assert len(queries) == 3  # Only the bounded shared-node query repeats; the name directory is cached.


def test_directory_cache_refresh_and_endpoint_isolation(monkeypatch):
    """Refresh the name cache daily and never reuse one configured server's directory for another."""
    queries = mock_union_service(monkeypatch)
    monkeypatch.setattr(street_directory, "monotonic", lambda: 86400)
    assert detect_location(VANESS_TRANSCRIPT).status == "resolved"
    assert detect_location(VANESS_TRANSCRIPT).status == "resolved"
    assert sum(query["$select"] == "st_name,st_type" for query in queries) == 1
    monkeypatch.setattr(street_directory, "monotonic", lambda: 2 * 86400)
    assert detect_location(VANESS_TRANSCRIPT).status == "resolved"
    from app.config import settings

    monkeypatch.setattr(settings, "call_intersections_url", "https://city.example/streets")
    assert detect_location(VANESS_TRANSCRIPT).status == "resolved"
    assert sum(query["$select"] == "st_name,st_type" for query in queries) == 3


def test_location_answer_flows_through_worker_and_start(system, monkeypatch):
    """A normalized location starts the real call workflow while retaining the machine transcript verbatim."""
    from app import call_worker
    from app.transcription import TranscriptResult
    from call_helpers import COORDINATOR

    class RecordedAnswer:
        """Supply the reported transcript without invoking a paid transcription provider."""

        def transcribe(self, *args):
            """Return the uncorrected transcript so normalization remains separate from speech provenance."""
            return TranscriptResult(text=VANESS_TRANSCRIPT)

    client, _ = system
    mock_union_service(monkeypatch)
    monkeypatch.setattr(call_worker, "get_transcription_adapter", RecordedAnswer)
    queued = client.post("/calls/sample/collision", headers=COORDINATOR).json()
    assert call_worker.process_one_call()
    call = client.get(f"/calls/{queued['id']}", headers=COORDINATOR).json()
    assert call["original_transcript"] == VANESS_TRANSCRIPT
    assert call["detected_location"]["address"] == "Van Ness & Union"
    started = client.post(
        f"/calls/{call['id']}/start",
        headers=COORDINATOR,
        json={"category": "collision", "version": call["version"]},
    )
    assert started.status_code == 200, started.text
    assert started.json()["confirmed_address"] == "Van Ness & Union"
    assert started.json()["reviewed_transcript"] == VANESS_TRANSCRIPT
    assert started.json()["report_id"] and started.json()["plan_id"]


@pytest.mark.parametrize(
    "first,second,expected",
    [
        ("VANESS", "VAN NESS", True),
        ("GRENEWICH", "GREENWICH", True),
        ("VANEZZ", "VAN NESS", False),
        ("UNON", "UNION", True),
        ("UNION", "UNION", False),
    ],
)
def test_bounded_edit_distance(first, second, expected):
    """Only a single character edit or adjacent transposition is tolerated."""
    assert street_directory.one_edit_apart(first, street_directory.compact_name(second)) is expected


def test_ambiguous_and_double_corrections_remain_unknown(monkeypatch):
    """A similar name is not enough: ambiguous spellings and two misspellings require more evidence."""
    directory = (
        street_directory.Street("VAN NESS", "AVE"),
        street_directory.Street("UNION", "ST"),
        street_directory.Street("GREENWICH", "ST"),
    )
    monkeypatch.setattr(street_directory, "load_street_directory", lambda *_: directory)
    assert street_directory.canonical_pair(
        street_directory.Street("VANESS", None), street_directory.Street("UNION", None), "city"
    ) == (street_directory.Street("VAN NESS", None), street_directory.Street("UNION", None))
    assert (
        street_directory.canonical_pair(
            street_directory.Street("VANESS", None), street_directory.Street("GRENEWICH", None), "city"
        )
        is None
    )
    ambiguous = directory + (street_directory.Street("VANESA", "AVE"),)
    assert street_directory.canonical_street(street_directory.Street("VANESS", None), ambiguous)[0] is None
    assert street_directory.canonical_street(street_directory.Street("UNON", None), directory)[0] is None
    assert street_directory.canonical_street(street_directory.Street("VANESS", "RD"), directory)[0] is None


def test_ordinary_dialogue_is_not_a_location_answer():
    """Medical descriptions and ordinary conjunctions must not become competing location candidates."""
    for transcript in [
        "One person is unresponsive and not breathing normally. Please hurry.",
        "What happened? A car and a bicycle. Please hurry.",
        "I need help with my arm and leg.",
    ]:
        assert spoken_intersections(transcript, []) == []


@pytest.mark.parametrize("mode", ["timeout", "malformed", "oversized", "truncated"])
def test_directory_failure_does_not_cache_or_guess(monkeypatch, mode):
    """Unavailable, invalid and partial dictionaries cannot justify a unique correction or poison the cache."""
    requests = []

    def handler(request):
        """Fail the street-directory request before any location can be inferred."""
        requests.append(request)
        if mode == "timeout":
            raise httpx.ReadTimeout("private provider detail")
        if mode == "oversized":
            return httpx.Response(200, content=b"x" * 270000)
        if mode == "truncated":
            return httpx.Response(200, json=[{"st_name": "UNION", "st_type": "ST"}] * 5000)
        return httpx.Response(200, json=[{"unexpected": "shape"}])

    original = httpx.Client
    monkeypatch.setattr(
        httpx, "Client", lambda **kwargs: original(transport=httpx.MockTransport(handler), **kwargs)
    )
    for _ in range(2):
        result = detect_location(VANESS_TRANSCRIPT)
        assert result.status == "unavailable" and result.latitude is None
        assert "private provider detail" not in result.reason
    assert len(requests) == 2
