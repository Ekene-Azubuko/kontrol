"""Cache official street names and conservatively normalize speech-to-text spelling errors."""

import json
import re
from dataclasses import dataclass
from functools import lru_cache
from time import monotonic

import httpx
from pydantic import Field

from .schemas import StrictModel

STREET_TYPES = {
    "STREET": "ST",
    "ST": "ST",
    "AVENUE": "AVE",
    "AVE": "AVE",
    "ROAD": "RD",
    "RD": "RD",
    "BOULEVARD": "BLVD",
    "BLVD": "BLVD",
    "DRIVE": "DR",
    "DR": "DR",
    "LANE": "LN",
    "LN": "LN",
    "WAY": "WAY",
    "COURT": "CT",
    "CT": "CT",
    "PLACE": "PL",
    "PL": "PL",
    "TERRACE": "TER",
    "TER": "TER",
}


@dataclass(frozen=True)
class Street:
    """Represent a street name with an optional explicitly spoken street type."""

    name: str
    street_type: str | None


class DirectoryStreet(StrictModel):
    """Validate the two projected columns in the city's distinct street-name directory."""

    st_name: str = Field(min_length=1, max_length=100)
    # Socrata omits null columns, including the suffix on names such as AVENUE B.
    st_type: str = Field(default="", max_length=20)


def normalize_street(value: str) -> Street:
    """Normalize case, whitespace, suffix abbreviations and numeric ordinal street names."""
    words = value.upper().replace("’", "'").split()
    street_type = STREET_TYPES.get(words[-1]) if words else None
    if street_type:
        words.pop()
    name = " ".join(words)
    ordinal = re.fullmatch(r"(\d{1,2})(ST|ND|RD|TH)", name)
    if ordinal:
        name = f"{int(ordinal[1]):02d}{ordinal[2]}"
    return Street(name, street_type)


def fetch_street_data(url: str, query: dict[str, str], limit: int) -> list[object]:
    """Bound city-data requests and reject truncated responses instead of assuming uniqueness."""
    with httpx.Client(timeout=8, follow_redirects=True) as client:
        with client.stream(
            "GET",
            url,
            headers={"User-Agent": "Kontrol-Simulation/1.0"},
            params={**query, "$limit": str(limit)},
        ) as response:
            response.raise_for_status()
            body = bytearray()
            for chunk in response.iter_bytes(chunk_size=8192):
                body.extend(chunk)
                if len(body) > 262144:
                    raise ValueError("Street-data response too large")
    rows = json.loads(body)
    if not isinstance(rows, list) or len(rows) >= limit:
        raise ValueError("Incomplete or invalid street-data response")
    return rows


@lru_cache(maxsize=4)
def load_street_directory(url: str, refresh_period: int) -> tuple[Street, ...]:
    """Cache validated public names for one daily refresh period; errors are never cached."""
    rows = fetch_street_data(
        url, {"$select": "st_name,st_type", "$group": "st_name,st_type", "$order": "st_name,st_type"}, 5000
    )
    entries = [DirectoryStreet.model_validate(row) for row in rows]
    return tuple(Street(row.st_name, row.st_type) for row in entries)


def compact_name(name: str) -> str:
    """Ignore spacing and punctuation while retaining every letter and digit of a street name."""
    return re.sub(r"[^A-Z0-9]", "", name)


def one_edit_apart(first: str, second: str) -> bool:
    """Allow one insertion, deletion, substitution, or adjacent transposition, never phonetic guessing."""
    if abs(len(first) - len(second)) > 1:
        return False
    if len(first) > len(second):
        first, second = second, first
    for index, character in enumerate(first):
        if character == second[index]:
            continue
        if len(first) != len(second):
            return first[index:] == second[index + 1 :]
        return first[index + 1 :] == second[index + 1 :] or (
            first[index : index + 2] == second[index : index + 2][::-1]
            and first[index + 2 :] == second[index + 2 :]
        )
    return len(second) - len(first) == 1


def canonical_street(street: Street, directory: tuple[Street, ...]) -> tuple[Street | None, bool]:
    """Prefer exact names; accept a unique one-edit correction only for names of at least five letters."""
    allowed = {
        row.name for row in directory if not street.street_type or row.street_type == street.street_type
    }
    compact = compact_name(street.name)
    exact = {name for name in allowed if compact_name(name) == compact}
    if exact:
        return (Street(next(iter(exact)), street.street_type), False) if len(exact) == 1 else (None, False)
    close = {name for name in allowed if len(compact) >= 5 and one_edit_apart(compact, compact_name(name))}
    return (Street(next(iter(close)), street.street_type), True) if len(close) == 1 else (None, False)


def canonical_pair(first: Street, second: Street, url: str) -> tuple[Street, Street] | None:
    """Normalize against city names while requiring at least one exact cross-street anchor."""
    directory = load_street_directory(url, int(monotonic() // 86400))
    first_match, first_corrected = canonical_street(first, directory)
    second_match, second_corrected = canonical_street(second, directory)
    # Two independently misspelled names provide too little evidence for an automatic incident pin.
    if not first_match or not second_match or (first_corrected and second_corrected):
        return None
    if first_match.name == second_match.name:
        return None
    return first_match, second_match
