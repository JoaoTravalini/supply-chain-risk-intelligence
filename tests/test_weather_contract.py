from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from supplychain.contracts import WeatherObservationPayload

SCHEMA_PATH = Path("schemas/events/weather-observation-v1.schema.json")


def make_weather_payload(**overrides: object) -> WeatherObservationPayload:
    data: dict[str, object] = {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "temperature_2m_c": 18.4,
        "relative_humidity_2m_pct": 73.0,
        "precipitation_mm": 0.2,
        "rain_mm": 0.2,
        "snowfall_cm": 0.0,
        "weather_code": 3,
        "wind_speed_10m_kmh": 12.5,
        "wind_gusts_10m_kmh": 24.0,
    }
    data.update(overrides)
    return WeatherObservationPayload.model_validate(data)


def test_valid_weather_payload_construction() -> None:
    payload = make_weather_payload()

    assert payload.latitude == 47.6062
    assert payload.temperature_2m_c == 18.4
    assert payload.weather_code == 3


def test_weather_payload_public_api() -> None:
    assert WeatherObservationPayload.__name__ == "WeatherObservationPayload"


def test_weather_payload_rejects_unknown_fields() -> None:
    with pytest.raises(ValidationError):
        make_weather_payload(risk_score=0.7)


def test_weather_payload_is_immutable() -> None:
    payload = make_weather_payload()

    with pytest.raises(ValidationError):
        payload.temperature_2m_c = 20.0


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", -90.1),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("longitude", 180.1),
        ("relative_humidity_2m_pct", -0.1),
        ("relative_humidity_2m_pct", 100.1),
        ("precipitation_mm", -0.1),
        ("rain_mm", -0.1),
        ("snowfall_cm", -0.1),
        ("wind_speed_10m_kmh", -0.1),
        ("wind_gusts_10m_kmh", -0.1),
        ("weather_code", -1),
        ("weather_code", 100),
    ],
)
def test_weather_payload_rejects_invalid_numeric_ranges(field: str, value: float) -> None:
    with pytest.raises(ValidationError):
        make_weather_payload(**{field: value})


@pytest.mark.parametrize(
    "field",
    [
        "latitude",
        "longitude",
        "temperature_2m_c",
        "relative_humidity_2m_pct",
        "precipitation_mm",
        "rain_mm",
        "snowfall_cm",
        "weather_code",
        "wind_speed_10m_kmh",
        "wind_gusts_10m_kmh",
    ],
)
def test_weather_payload_rejects_boolean_numeric_inputs(field: str) -> None:
    with pytest.raises(ValidationError):
        make_weather_payload(**{field: True})


def test_weather_payload_rejects_string_weather_code() -> None:
    with pytest.raises(ValidationError):
        make_weather_payload(weather_code="3")


def test_weather_payload_accepts_negative_temperature() -> None:
    assert make_weather_payload(temperature_2m_c=-12.5).temperature_2m_c == -12.5


def test_weather_payload_schema_artifact_matches_model() -> None:
    generated_schema = WeatherObservationPayload.model_json_schema()
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == generated_schema
