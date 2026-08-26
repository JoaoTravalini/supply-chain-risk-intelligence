from __future__ import annotations

from datetime import UTC, datetime
from typing import cast

import httpx
import pytest

from supplychain.contracts import EntityReference, EventType, LocationMetadata
from supplychain.contracts.events import CanonicalEvent
from supplychain.integrations import (
    OPEN_METEO_CURRENT_VARIABLES,
    OPEN_METEO_FORECAST_ENDPOINT,
    ExternalHttpClient,
    ExternalSourcePayloadError,
    JsonObject,
    OpenMeteoWeatherAdapter,
    generate_open_meteo_source_event_id,
    normalize_open_meteo_coordinate,
)


def open_meteo_response(**overrides: object) -> JsonObject:
    payload: dict[str, object] = {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "generationtime_ms": 0.04,
        "utc_offset_seconds": 0,
        "timezone": "GMT",
        "timezone_abbreviation": "GMT",
        "elevation": 53.0,
        "current_units": {
            "time": "unixtime",
            "interval": "seconds",
            "temperature_2m": "\u00b0C",
            "relative_humidity_2m": "%",
            "precipitation": "mm",
            "rain": "mm",
            "snowfall": "cm",
            "weather_code": "wmo code",
            "wind_speed_10m": "km/h",
            "wind_gusts_10m": "km/h",
        },
        "current": {
            "time": 1_787_701_200,
            "interval": 900,
            "temperature_2m": 18.4,
            "relative_humidity_2m": 73.0,
            "precipitation": 0.2,
            "rain": 0.2,
            "snowfall": 0.0,
            "weather_code": 3,
            "wind_speed_10m": 12.5,
            "wind_gusts_10m": 24.0,
        },
    }
    payload.update(overrides)
    return cast(JsonObject, payload)


def make_adapter(
    payload: JsonObject | None = None,
) -> tuple[OpenMeteoWeatherAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=open_meteo_response() if payload is None else payload)

    client = ExternalHttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    return OpenMeteoWeatherAdapter(client), requests


def fetch_event(
    payload: JsonObject | None = None,
    *,
    latitude: float = 47.6062,
    longitude: float = -122.3321,
    correlation_id: str = "corr-weather-001",
    entity: EntityReference | None = None,
    location: LocationMetadata | None = None,
    ingested_at: datetime | None = None,
) -> tuple[CanonicalEvent, list[httpx.Request]]:
    adapter, requests = make_adapter(payload)
    event = adapter.fetch_current_weather_event(
        latitude=latitude,
        longitude=longitude,
        correlation_id=correlation_id,
        entity=entity,
        location=location,
        ingested_at=ingested_at,
    )
    return event, requests


def test_open_meteo_request_uses_correct_endpoint_and_get() -> None:
    _, requests = fetch_event()

    assert requests[0].method == "GET"
    assert f"{requests[0].url.scheme}://{requests[0].url.host}{requests[0].url.path}" == (
        OPEN_METEO_FORECAST_ENDPOINT
    )


def test_open_meteo_request_sends_required_current_variables() -> None:
    _, requests = fetch_event()

    current = requests[0].url.params["current"]

    assert current.split(",") == list(OPEN_METEO_CURRENT_VARIABLES)


def test_open_meteo_request_sends_coordinates() -> None:
    _, requests = fetch_event(latitude=47.6, longitude=-122.3)

    assert requests[0].url.params["latitude"] == "47.6"
    assert requests[0].url.params["longitude"] == "-122.3"


def test_open_meteo_request_sends_utc_timeformat_and_units() -> None:
    _, requests = fetch_event()
    params = requests[0].url.params

    assert params["timezone"] == "UTC"
    assert params["timeformat"] == "unixtime"
    assert params["temperature_unit"] == "celsius"
    assert params["wind_speed_unit"] == "kmh"
    assert params["precipitation_unit"] == "mm"


def test_open_meteo_request_does_not_send_api_key() -> None:
    _, requests = fetch_event()
    query = str(requests[0].url.query)

    assert "key" not in query.lower()
    assert "token" not in query.lower()


@pytest.mark.parametrize(
    ("latitude", "longitude"),
    [(-90.1, 0.0), (90.1, 0.0), (0.0, -180.1), (0.0, 180.1)],
)
def test_invalid_input_coordinates_are_rejected_without_network(
    latitude: float,
    longitude: float,
) -> None:
    adapter, requests = make_adapter()

    with pytest.raises(ValueError):
        adapter.fetch_current_weather_event(
            latitude=latitude,
            longitude=longitude,
            correlation_id="corr-weather-001",
        )

    assert requests == []


def test_valid_current_response_parses_successfully() -> None:
    event, _ = fetch_event()

    assert event.payload["temperature_2m_c"] == 18.4
    assert event.payload["weather_code"] == 3


def test_provider_timestamp_becomes_timezone_aware_utc_event_time() -> None:
    event, _ = fetch_event()

    assert event.event_time == datetime.fromtimestamp(1_787_701_200, UTC)
    assert event.event_time.tzinfo is UTC


def test_non_zero_provider_utc_offset_is_rejected() -> None:
    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(open_meteo_response(utc_offset_seconds=3600))


def test_missing_current_section_is_rejected() -> None:
    payload = open_meteo_response()
    del payload["current"]

    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(payload)


def test_missing_required_weather_field_is_rejected() -> None:
    payload = open_meteo_response()
    current = cast(dict[str, object], payload["current"])
    del current["temperature_2m"]

    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(payload)


def test_invalid_weather_numeric_value_is_rejected() -> None:
    payload = open_meteo_response()
    current = cast(dict[str, object], payload["current"])
    current["relative_humidity_2m"] = 101.0

    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(payload)


def test_mismatched_temperature_unit_is_rejected() -> None:
    payload = open_meteo_response()
    units = cast(dict[str, object], payload["current_units"])
    units["temperature_2m"] = "\u00b0F"

    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(payload)


def test_mismatched_wind_unit_is_rejected() -> None:
    payload = open_meteo_response()
    units = cast(dict[str, object], payload["current_units"])
    units["wind_speed_10m"] = "mph"

    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(payload)


def test_mismatched_precipitation_unit_is_rejected() -> None:
    payload = open_meteo_response()
    units = cast(dict[str, object], payload["current_units"])
    units["precipitation"] = "inch"

    with pytest.raises(ExternalSourcePayloadError):
        fetch_event(payload)


def test_malformed_provider_response_maps_to_project_safe_payload_error() -> None:
    with pytest.raises(ExternalSourcePayloadError) as exc_info:
        fetch_event(cast(JsonObject, {"current": "malformed"}))

    assert exc_info.value.method == "GET"
    assert exc_info.value.safe_url == OPEN_METEO_FORECAST_ENDPOINT


def test_same_provider_location_and_time_create_same_source_event_id() -> None:
    observed_at = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    first = generate_open_meteo_source_event_id(
        latitude=47.6062,
        longitude=-122.3321,
        observed_at=observed_at,
    )
    second = generate_open_meteo_source_event_id(
        latitude=47.6062,
        longitude=-122.3321,
        observed_at=observed_at,
    )

    assert first == second


def test_different_observation_time_changes_source_event_id() -> None:
    first = generate_open_meteo_source_event_id(
        latitude=47.6062,
        longitude=-122.3321,
        observed_at=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )
    second = generate_open_meteo_source_event_id(
        latitude=47.6062,
        longitude=-122.3321,
        observed_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
    )

    assert first != second


def test_different_response_latitude_changes_source_event_id() -> None:
    first, _ = fetch_event()
    second, _ = fetch_event(open_meteo_response(latitude=47.7))

    assert first.source.source_event_id != second.source.source_event_id


def test_different_response_longitude_changes_source_event_id() -> None:
    first, _ = fetch_event()
    second, _ = fetch_event(open_meteo_response(longitude=-122.4))

    assert first.source.source_event_id != second.source.source_event_id


def test_changing_weather_measurements_does_not_change_source_event_id() -> None:
    first, _ = fetch_event()
    payload = open_meteo_response()
    current = cast(dict[str, object], payload["current"])
    current["temperature_2m"] = 22.0
    second, _ = fetch_event(payload)

    assert first.source.source_event_id == second.source.source_event_id


def test_changing_entity_does_not_change_source_event_id() -> None:
    first, _ = fetch_event()
    second, _ = fetch_event(entity=EntityReference(type="supplier", id="SUP-000001"))

    assert first.source.source_event_id == second.source.source_event_id


def test_changing_correlation_id_does_not_change_source_event_id() -> None:
    first, _ = fetch_event(correlation_id="corr-weather-001")
    second, _ = fetch_event(correlation_id="corr-weather-002")

    assert first.source.source_event_id == second.source.source_event_id


def test_changing_ingestion_time_does_not_change_source_event_id() -> None:
    first, _ = fetch_event(ingested_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC))
    second, _ = fetch_event(ingested_at=datetime(2026, 8, 25, 12, 2, tzinfo=UTC))

    assert first.source.source_event_id == second.source.source_event_id


def test_coordinate_normalization_is_deterministic() -> None:
    assert normalize_open_meteo_coordinate(47.6) == "47.600000"
    assert normalize_open_meteo_coordinate(47.6000004) == "47.600000"
    assert normalize_open_meteo_coordinate(-122.3321) == "-122.332100"


def test_event_type_is_weather_observation_recorded() -> None:
    event, _ = fetch_event()

    assert event.event_type is EventType.WEATHER_OBSERVATION_RECORDED


def test_source_provider_endpoint_and_source_event_id_are_set_safely() -> None:
    event, _ = fetch_event()

    assert event.source.provider == "open-meteo"
    assert event.source.endpoint == OPEN_METEO_FORECAST_ENDPOINT
    assert "?" not in event.source.endpoint
    assert event.source.source_event_id.startswith("open-meteo-current:")


def test_payload_matches_weather_observation_payload_shape() -> None:
    event, _ = fetch_event()

    assert event.payload == {
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


def test_supplied_entity_reference_is_preserved() -> None:
    entity = EntityReference(type="supplier", id="SUP-000001")
    event, _ = fetch_event(entity=entity)

    assert event.entity == entity


def test_supplied_location_context_is_preserved() -> None:
    location = LocationMetadata(country_code="US", region="WA")
    event, _ = fetch_event(location=location)

    assert event.location == location


def test_same_logical_source_record_can_have_different_event_id_same_dedup_key() -> None:
    first, _ = fetch_event()
    second, _ = fetch_event()

    assert first.event_id != second.event_id
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_entity_does_not_change_deduplication_key() -> None:
    first, _ = fetch_event()
    second, _ = fetch_event(entity=EntityReference(type="supplier", id="SUP-000001"))

    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_correlation_id_is_preserved_but_excluded_from_deduplication_key() -> None:
    first, _ = fetch_event(correlation_id="corr-weather-001")
    second, _ = fetch_event(correlation_id="corr-weather-002")

    assert first.metadata.correlation_id == "corr-weather-001"
    assert second.metadata.correlation_id == "corr-weather-002"
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_adapter_uses_stable_producer_metadata() -> None:
    event, _ = fetch_event()

    assert event.metadata.producer == "open-meteo-weather-adapter"
    assert event.metadata.producer_version == "1.0.0"
