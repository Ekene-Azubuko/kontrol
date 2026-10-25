"""Extract spoken cross streets and match their shared node in San Francisco's public GIS."""

import re
from dataclasses import dataclass
from typing import Literal

from pydantic import Field

from .config import settings
from .schemas import StrictModel
from .street_directory import Street, canonical_pair, fetch_street_data, normalize_street

STREET_WORD = r"[a-z0-9][a-z0-9'’-]*"
STREET_NAME = rf"{STREET_WORD}(?:[ \t]+{STREET_WORD}){{0,4}}?"
PAIR = rf"(?P<first>{STREET_NAME})\s*(?:\band\b|&|/)\s*(?P<second>{STREET_NAME})"
PAIR_END = r"(?=\s*(?:[.,!?;:\n]|$|\b(?:in|where|by|there|with|right now|and then)\b))"
FILLERS = r"(?:(?:um|uh|erm|well|okay|ok)[,\s]+)*"
CROSS_STREETS = re.compile(
    rf"\b(?:intersection\s+(?:of\s+)?|junction\s+(?:of\s+)?|corner\s+(?:of\s+)?|at\s+|near\s+|on\s+)"
    rf"{PAIR}{PAIR_END}",
    re.IGNORECASE,
)
LOCATION_ANSWER = re.compile(
    r"\b(?:(?:what(?:'s| is)|tell me)\s+(?:your|the)\s+(?:location|address)"
    r"|where\s+(?:are you|did (?:this|it) happen))[^?.!\n]{0,40}[?.:\n]\s*"
    rf"(?:caller:\s*)?{FILLERS}{PAIR}{PAIR_END}",
    re.IGNORECASE,
)
BARE_CROSS_STREETS = re.compile(
    rf"(?P<first>{STREET_NAME})\s*(?:&|/)\s*(?P<second>{STREET_NAME})"
    rf"(?=\s*(?:[.,!?;:\n]|$))",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class SpokenIntersection:
    """Retain the caller's cross-street phrase alongside normalized lookup keys."""

    first: Street
    second: Street
    evidence: str


class IntersectionMatch(StrictModel):
    """Validate a unique shared GIS node within the application's SF exercise area."""

    address: str = Field(min_length=3, max_length=160)
    latitude: float = Field(ge=37.705, le=37.825)
    longitude: float = Field(ge=-122.525, le=-122.35)
    node_id: str = Field(min_length=1, max_length=80)


class GISGeometry(StrictModel):
    """Validate the point geometry returned by the projected public dataset query."""

    type: Literal["Point"]
    coordinates: tuple[float, float]


class GISStreetNode(StrictModel):
    """Keep the public GIS response limited to known node, street and point fields."""

    cnn: str = Field(min_length=1, max_length=80)
    st_name: str = Field(min_length=1, max_length=100)
    st_type: str = Field(default="", max_length=20)
    the_geom: GISGeometry


def spoken_intersections(transcript: str, excluded_spans: list[tuple[int, int]]) -> list[SpokenIntersection]:
    """Recognize cross streets and short location answers without treating every conjunction as a place."""
    found: dict[tuple[str, str], SpokenIntersection] = {}
    matched_spans = list(excluded_spans)
    plain_pair = re.compile(
        rf"\A\s*(?:caller:\s*)?{FILLERS}{PAIR}[.!?]?\s*\Z",
        re.IGNORECASE,
    )
    for pattern in [CROSS_STREETS, LOCATION_ANSWER, BARE_CROSS_STREETS, plain_pair]:
        for match in pattern.finditer(transcript):
            if any(match.start() < end and match.end() > start for start, end in matched_spans):
                continue
            first, second = normalize_street(match["first"]), normalize_street(match["second"])
            if not first.name or not second.name or first.name == second.name:
                continue
            matched_spans.append(match.span())
            key = tuple(sorted([first.name, second.name]))
            found[key] = SpokenIntersection(
                first, second, f"{match['first'].strip()} & {match['second'].strip()}"
            )
    return list(found.values())


def lookup_intersection(intersection: SpokenIntersection) -> IntersectionMatch | None:
    """Normalize spoken names and require one shared GIS node, never an arbitrary street midpoint."""
    if not settings.call_intersections_url:
        return None
    pair = canonical_pair(intersection.first, intersection.second, settings.call_intersections_url)
    if pair is None:
        return None
    # Escape query literals even though the parser already restricts street-name characters.
    names = [street.name.replace("'", "''") for street in pair]
    address = " & ".join(
        f"{street.name.title()} {street.street_type.title()}" if street.street_type else street.name.title()
        for street in pair
    )
    rows = fetch_street_data(
        settings.call_intersections_url,
        {"$select": "cnn,st_name,st_type,the_geom", "$where": f"st_name in ('{names[0]}','{names[1]}')"},
        1000,
    )
    streets: dict[str, set[int]] = {}
    points: dict[str, IntersectionMatch] = {}
    for value in rows:
        row = GISStreetNode.model_validate(value)
        for index, street in enumerate(pair):
            if row.st_name != street.name or (street.street_type and row.st_type != street.street_type):
                continue
            longitude, latitude = row.the_geom.coordinates
            point = IntersectionMatch(
                address=address, latitude=latitude, longitude=longitude, node_id=row.cnn
            )
            if row.cnn in points and (points[row.cnn].latitude, points[row.cnn].longitude) != (
                latitude,
                longitude,
            ):
                raise ValueError("Conflicting geometry for a shared street node")
            points[row.cnn] = point
            streets.setdefault(row.cnn, set()).add(index)
    # The city's dataset has one row per street at a node; a valid crossing must contain both.
    matches = [points[node_id] for node_id, indices in streets.items() if indices == {0, 1}]
    unique = {(point.latitude, point.longitude) for point in matches}
    return matches[0] if len(unique) == 1 else None
