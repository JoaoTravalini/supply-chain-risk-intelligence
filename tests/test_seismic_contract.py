from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path

import pytest
from pydantic import ValidationError

from supplychain.contracts import SeismicEventPayload

SCHEMA_PATH = Path("schemas/events/seismic-event-v1.schema.json")


def make_seismic_payload(**overrides: object) -> SeismicEventPayload:
    data: dict[str, object] = {
        "latitude": 37.251,
        "longitude": -121.642,
        "depth_km": 7.2,
        "magnitude": 4.6,
        "magnitude_type": "mw",
        "place": "12 km E of Example, CA",
        "status": "reviewed",
        "tsunami": False,
        "significance": 326,
        "source_updated_at": datetime(2026, 8, 26, 12, 30, tzinfo=UTC),
    }
    data.update(overrides)
    return SeismicEventPayload.model_validate(data)


def test_valid_seismic_payload_construction() -> None:
    payload = make_seismic_payload()

    assert payload.latitude == 37.251
    assert payload.depth_km == 7.2
    assert payload.source_updated_at.tzinfo is UTC


def test_seismic_payload_public_api() -> None:
    assert SeismicEventPayload.__name__ == "SeismicEventPayload"


def test_seismic_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_seismic_payload(risk_score=0.8)


def test_seismic_payload_is_immutable() -> None:
    payload = make_seismic_payload()

    with pytest.raises(ValidationError):
        payload.magnitude = 5.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", -90.1),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("longitude", 180.1),
        ("depth_km", -100.1),
        ("depth_km", 1000.1),
        ("magnitude", -10.1),
        ("magnitude", 10.1),
        ("significance", -1),
    ],
)
def test_seismic_payload_rejects_invalid_numeric_ranges(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_seismic_payload(**{field: value})


@pytest.mark.parametrize(
    "field",
    ["latitude", "longitude", "depth_km", "magnitude", "significance"],
)
def test_seismic_payload_rejects_boolean_numeric_inputs(field: str) -> None:
    with pytest.raises(ValidationError):
        make_seismic_payload(**{field: True})


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("magnitude_type", "   "),
        ("place", "   "),
    ],
)
def test_seismic_payload_rejects_blank_strings(field: str, value: str) -> None:
    with pytest.raises(ValidationError):
        make_seismic_payload(**{field: value})


def test_seismic_payload_allows_absent_magnitude_type() -> None:
    assert make_seismic_payload(magnitude_type=None).magnitude_type is None


def test_seismic_payload_rejects_unknown_status() -> None:
    with pytest.raises(ValidationError):
        make_seismic_payload(status="deleted")


def test_seismic_payload_rejects_naive_source_updated_at() -> None:
    with pytest.raises(ValidationError):
        make_seismic_payload(source_updated_at=datetime(2026, 8, 26, 12, 30))


def test_seismic_payload_schema_artifact_matches_model() -> None:
    generated_schema = SeismicEventPayload.model_json_schema()
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == generated_schema
