"""Resolve spoken exercise locations without substituting the caller's device position."""

import json
import re
from typing import Literal, Self

import httpx
from pydantic import Field, model_validator

from .config import settings
from .schemas import StrictModel
from .street_intersections import lookup_intersection, spoken_intersections


class DetectedLocation(StrictModel):
    """Keep automatic location inference separate from human verification and device metadata."""

    status: Literal["resolved", "unavailable"]
    address: str | None = Field(default=None, max_length=160)
    latitude: float | None = Field(default=None, ge=-90, le=90)
    longitude: float | None = Field(default=None, ge=-180, le=180)
    source: Literal["exercise_gazetteer", "photon", "sf_intersections", "unavailable"]
    input_source: Literal["transcript", "dispatcher_address"] = "transcript"
    input_address: str | None = Field(default=None, min_length=2, max_length=160)
    reference: str | None = Field(default=None, max_length=300)
    evidence: str | None = Field(default=None, max_length=300)
    reason: str = Field(max_length=300)

    @model_validator(mode="after")
    def complete_location(self) -> Self:
        """Never permit a resolved result with missing coordinates or an empty address."""
        if self.status == "resolved" and (
            not self.address or self.latitude is None or self.longitude is None
        ):
            raise ValueError("Resolved locations require an address and both coordinates")
        return self


# These are documented exercise sites, not invented geocoding results for arbitrary real addresses.
AUTOMATIC_LOCATION_LIMITATION = (
    "Incident location was inferred automatically from the transcript and is not human-verified."
)
EDITED_LOCATION_LIMITATION = (
    "Incident coordinates were inferred from a dispatcher-edited address and are not human-verified."
)

EXERCISE_LOCATIONS = [
    (
        r"\bmarket(?: street)?\s*(?:and|&|at)\s*(?:eighth|8th)(?: street)?\b",
        "Market & 8th exercise area",
        37.777,
        -122.414,
    ),
    (r"\bmission exercise block\b", "Mission exercise block", 37.758, -122.421),
    (r"\brichmond exercise block\b", "Richmond exercise block", 37.780, -122.460),
]
STREET_SUFFIX = r"(?:street|st|avenue|ave|road|rd|boulevard|blvd|drive|dr|lane|ln|way|court|ct|place|pl)\b"
NUMBERED_ADDRESS = re.compile(
    r"\b\d{1,6}\s+(?:(?:[a-z][a-z'-]*|\d{1,3}(?:st|nd|rd|th))\s+){1,5}" + STREET_SUFFIX, re.IGNORECASE
)


def unavailable(reason: str, evidence: str | None = None) -> DetectedLocation:
    """Return an explicit missing-location result, with no guessed coordinate fallback."""
    return DetectedLocation(status="unavailable", source="unavailable", reason=reason, evidence=evidence)


def address_tokens(value: str) -> set[str]:
    """Normalize common street abbreviations for conservative provider-result matching."""
    replacements = {
        "st": "street",
        "ave": "avenue",
        "rd": "road",
        "blvd": "boulevard",
        "dr": "drive",
        "ln": "lane",
        "ct": "court",
        "pl": "place",
    }
    return {replacements.get(word, word) for word in re.findall(r"[a-z0-9]+", value.lower())}


def geocode_address(address: str) -> DetectedLocation:
    """Query only the extracted address and accept one matching result in the SF exercise area."""
    if not settings.call_geocoding_url:
        return unavailable("Automatic geocoding is disabled for this address.", address)
    try:
        with httpx.Client(timeout=5) as client:
            with client.stream(
                "GET",
                settings.call_geocoding_url.rstrip("/"),
                headers={"User-Agent": "Kontrol-Simulation/1.0", "Accept": "application/json"},
                params={
                    "q": address,
                    "limit": 5,
                    "lang": "en",
                    "bbox": "-122.525,37.705,-122.35,37.825",
                },
            ) as response:
                response.raise_for_status()
                body = bytearray()
                for chunk in response.iter_bytes(chunk_size=8192):
                    body.extend(chunk)
                    if len(body) > 65536:
                        raise ValueError("Oversized geocoder response")
        features = json.loads(body)["features"]
        if not isinstance(features, list) or len(features) > 5:
            raise ValueError("Invalid geocoder response")
        candidates: list[DetectedLocation] = []
        for feature in features:
            geometry, properties = feature["geometry"], feature["properties"]
            if geometry["type"] != "Point" or len(geometry["coordinates"]) != 2:
                continue
            longitude, latitude = geometry["coordinates"]
            if not (-122.525 <= longitude <= -122.35 and 37.705 <= latitude <= 37.825):
                continue
            if str(properties.get("housenumber", "")) != address.split()[0]:
                continue
            provider_address = " ".join(
                str(properties.get(field, "")) for field in ["housenumber", "street", "name"]
            )
            if not address_tokens(address).issubset(address_tokens(provider_address)):
                continue
            candidates.append(
                DetectedLocation(
                    status="resolved",
                    address=address,
                    latitude=latitude,
                    longitude=longitude,
                    source="photon",
                    evidence=address,
                    reason="Automatically matched from location text; location is not human-verified.",
                )
            )
        # Distinct matches are ambiguous. Never select the first of multiple suggested locations.
        unique = {(round(row.latitude, 5), round(row.longitude, 5)) for row in candidates}
        if len(unique) == 1:
            return candidates[0]
        return unavailable(
            "No unique matching address was found in the San Francisco exercise area.", address
        )
    except Exception:
        return unavailable("The location service could not resolve this spoken address.", address)


def detect_location(transcript: str) -> DetectedLocation:
    """Resolve an explicit spoken exercise site or street address; missing and conflicting places stay unknown."""
    sites: list[DetectedLocation] = []
    site_spans: list[tuple[int, int]] = []
    for pattern, address, latitude, longitude in EXERCISE_LOCATIONS:
        match = re.search(pattern, transcript, re.IGNORECASE)
        if match:
            site_spans.append(match.span())
            sites.append(
                DetectedLocation(
                    status="resolved",
                    address=address,
                    latitude=latitude,
                    longitude=longitude,
                    source="exercise_gazetteer",
                    evidence=match.group(),
                    reason="Location text matched to the fictional exercise map; not human-verified.",
                )
            )
    addresses = {match.group().strip() for match in NUMBERED_ADDRESS.finditer(transcript)}
    intersections = spoken_intersections(transcript, site_spans)
    if len(sites) + len(addresses) + len(intersections) > 1:
        return unavailable("The supplied text mentions multiple locations; no incident pin was inferred.")
    if sites:
        return sites[0]
    if len(addresses) == 1:
        return geocode_address(next(iter(addresses)))
    if intersections:
        intersection = intersections[0]
        try:
            point = lookup_intersection(intersection)
            if point:
                return DetectedLocation(
                    status="resolved",
                    address=point.address,
                    latitude=point.latitude,
                    longitude=point.longitude,
                    source="sf_intersections",
                    evidence=intersection.evidence,
                    reference="https://data.sf.gov/d/gmfx-8h6i",
                    reason=f"Cross streets matched city street node {point.node_id}; location is not human-verified.",
                )
            return unavailable(
                "No unique matching street intersection was found in the San Francisco exercise area.",
                intersection.evidence,
            )
        except Exception:
            return unavailable(
                "The intersection was recognized, but the city location service is unavailable.",
                intersection.evidence,
            )
    return unavailable(
        "No clear street address, intersection, or exercise landmark was found in the supplied text."
    )
