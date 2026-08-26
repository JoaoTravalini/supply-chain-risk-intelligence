from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from typing import cast
from uuid import uuid4

import httpx
import pytest

from supplychain.contracts import EntityReference, EventType, SeismicEventPayload
from supplychain.contracts.events import CanonicalEvent
from supplychain.integrations import (
    USGS_QUERY_ENDPOINT,
    ExternalHttpClient,
    ExternalSourcePayloadError,
    JsonObject,
    UsgsSeismicAdapter,
    format_usgs_datetime,
)


def usgs_feature(**overrides: object) -> dict[str, object]:
    feature: dict[str, object] = {
        "type": "Feature",
        "id": "us7000abcd",
        "properties": {
            "mag": 4.6,
            "place": "12 km E of Example, CA",
            "time": 1_787_688_000_000,
            "updated": 1_787_691_600_000,
            "status": "reviewed",
            "tsunami": 0,
            "sig": 326,
            "magType": "mw",
            "type": "earthquake",
            "title": "M 4.6 - 12 km E of Example, CA",
        },
        "geometry": {
            "type": "Point",
            "coordinates": [-121.642, 37.251, 7.2],
        },
    }
    feature.update(overrides)
    return feature


def usgs_response(
    features: list[dict[str, object]] | None = None, **overrides: object
) -> JsonObject:
    payload: dict[str, object] = {
        "type": "FeatureCollection",
        "metadata": {
            "generated": 1_787_692_000_000,
            "url": USGS_QUERY_ENDPOINT,
            "title": "USGS Earthquakes",
            "status": 200,
            "api": "1.14.1",
            "count": len(features) if features is not None else 1,
        },
        "features": [usgs_feature()] if features is None else features,
    }
    payload.update(overrides)
    return cast(JsonObject, payload)


def make_adapter(
    payload: JsonObject | None = None,
) -> tuple[UsgsSeismicAdapter, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json=usgs_response() if payload is None else payload)

    client = ExternalHttpClient(transport=httpx.MockTransport(handler), sleep=lambda _: None)
    return UsgsSeismicAdapter(client), requests


def fetch_events(
    payload: JsonObject | None = None,
    *,
    latitude: float = 37.0,
    longitude: float = -122.0,
    start_time: datetime = datetime(2026, 8, 26, 0, 0, tzinfo=UTC),
    end_time: datetime = datetime(2026, 8, 27, 0, 0, tzinfo=UTC),
    max_radius_km: float = 250.0,
    min_magnitude: float = 4.0,
    limit: int = 100,
    correlation_id: str = "corr-seismic-001",
    entity: EntityReference | None = None,
    ingested_at: datetime | None = None,
) -> tuple[tuple[CanonicalEvent, ...], list[httpx.Request]]:
    adapter, requests = make_adapter(payload)
    events = adapter.fetch_nearby_events(
        latitude=latitude,
        longitude=longitude,
        start_time=start_time,
        end_time=end_time,
        max_radius_km=max_radius_km,
        min_magnitude=min_magnitude,
        limit=limit,
        correlation_id=correlation_id,
        entity=entity,
        ingested_at=ingested_at,
    )
    return events, requests


def first_event(
    payload: JsonObject | None = None,
    *,
    correlation_id: str = "corr-seismic-001",
    entity: EntityReference | None = None,
) -> CanonicalEvent:
    events, _ = fetch_events(payload, correlation_id=correlation_id, entity=entity)
    return events[0]


def test_usgs_request_uses_correct_endpoint_and_get() -> None:
    _, requests = fetch_events()

    assert requests[0].method == "GET"
    assert f"{requests[0].url.scheme}://{requests[0].url.host}{requests[0].url.path}" == (
        USGS_QUERY_ENDPOINT
    )


def test_usgs_request_sends_required_format_and_event_type() -> None:
    _, requests = fetch_events()
    params = requests[0].url.params

    assert params["format"] == "geojson"
    assert params["eventtype"] == "earthquake"


def test_usgs_request_sends_location_radius_time_magnitude_limit_and_order() -> None:
    _, requests = fetch_events(latitude=37.1, longitude=-122.2, max_radius_km=125.5, limit=25)
    params = requests[0].url.params

    assert params["latitude"] == "37.1"
    assert params["longitude"] == "-122.2"
    assert params["maxradiuskm"] == "125.5"
    assert params["starttime"] == "2026-08-26T00:00:00Z"
    assert params["endtime"] == "2026-08-27T00:00:00Z"
    assert params["minmagnitude"] == "4.0"
    assert params["limit"] == "25"
    assert params["orderby"] == "time-asc"


def test_usgs_request_normalizes_aware_non_utc_times() -> None:
    offset = timezone(timedelta(hours=-4))
    _, requests = fetch_events(
        start_time=datetime(2026, 8, 25, 20, 0, tzinfo=offset),
        end_time=datetime(2026, 8, 26, 20, 0, tzinfo=offset),
    )

    assert requests[0].url.params["starttime"] == "2026-08-26T00:00:00Z"
    assert requests[0].url.params["endtime"] == "2026-08-27T00:00:00Z"


def test_usgs_request_does_not_send_api_key() -> None:
    _, requests = fetch_events()
    query = str(requests[0].url.query)

    assert "key" not in query.lower()
    assert "token" not in query.lower()


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("latitude", -90.1),
        ("latitude", 90.1),
        ("longitude", -180.1),
        ("longitude", 180.1),
        ("max_radius_km", 0.0),
        ("max_radius_km", 1000.1),
        ("limit", 0),
        ("limit", 501),
    ],
)
def test_invalid_query_inputs_are_rejected_without_network(field: str, value: object) -> None:
    adapter, requests = make_adapter()

    with pytest.raises(ValueError):
        adapter.fetch_nearby_events(
            latitude=cast(float, value) if field == "latitude" else 37.0,
            longitude=cast(float, value) if field == "longitude" else -122.0,
            start_time=datetime(2026, 8, 26, 0, 0, tzinfo=UTC),
            end_time=datetime(2026, 8, 27, 0, 0, tzinfo=UTC),
            max_radius_km=cast(float, value) if field == "max_radius_km" else 250.0,
            limit=cast(int, value) if field == "limit" else 100,
            correlation_id="corr-seismic-001",
        )

    assert requests == []


@pytest.mark.parametrize(
    ("start_time", "end_time"),
    [
        (datetime(2026, 8, 26, 0, 0), datetime(2026, 8, 27, 0, 0, tzinfo=UTC)),
        (datetime(2026, 8, 26, 0, 0, tzinfo=UTC), datetime(2026, 8, 27, 0, 0)),
        (datetime(2026, 8, 27, 0, 0, tzinfo=UTC), datetime(2026, 8, 26, 0, 0, tzinfo=UTC)),
        (datetime(2026, 8, 26, 0, 0, tzinfo=UTC), datetime(2026, 8, 26, 0, 0, tzinfo=UTC)),
    ],
)
def test_invalid_time_windows_are_rejected_without_network(
    start_time: datetime,
    end_time: datetime,
) -> None:
    adapter, requests = make_adapter()

    with pytest.raises(ValueError):
        adapter.fetch_nearby_events(
            latitude=37.0,
            longitude=-122.0,
            start_time=start_time,
            end_time=end_time,
            max_radius_km=250.0,
            correlation_id="corr-seismic-001",
        )

    assert requests == []


def test_format_usgs_datetime_rejects_naive_datetime() -> None:
    with pytest.raises(ValueError):
        format_usgs_datetime(datetime(2026, 8, 26, 0, 0))


def test_valid_feature_collection_maps_successfully() -> None:
    events, _ = fetch_events()

    assert len(events) == 1
    assert events[0].source.source_event_id == "us7000abcd"


def test_zero_feature_collection_returns_empty_tuple() -> None:
    events, _ = fetch_events(usgs_response(features=[]))

    assert events == ()


def test_feature_collection_without_count_uses_relevant_status_metadata() -> None:
    payload = usgs_response()
    metadata = cast(dict[str, object], payload["metadata"])
    del metadata["count"]

    events, _ = fetch_events(payload)

    assert len(events) == 1


def test_feature_collection_without_status_is_rejected() -> None:
    payload = usgs_response()
    metadata = cast(dict[str, object], payload["metadata"])
    del metadata["status"]

    with pytest.raises(ExternalSourcePayloadError):
        fetch_events(payload)


@pytest.mark.parametrize(
    "payload",
    [
        {"features": []},
        {"type": "NotAFeatureCollection", "metadata": {"count": 0}, "features": []},
        usgs_response(features=[usgs_feature(type="NotAFeature")]),
        usgs_response(features=[usgs_feature(geometry={"type": "LineString", "coordinates": []})]),
    ],
)
def test_malformed_geojson_is_rejected_safely(payload: dict[str, object]) -> None:
    with pytest.raises(ExternalSourcePayloadError) as exc_info:
        fetch_events(cast(JsonObject, payload))

    assert exc_info.value.method == "GET"
    assert exc_info.value.safe_url == USGS_QUERY_ENDPOINT


def test_geometry_coordinate_order_maps_longitude_latitude_depth_correctly() -> None:
    event = first_event()

    assert event.payload["longitude"] == -121.642
    assert event.payload["latitude"] == 37.251
    assert event.payload["depth_km"] == 7.2


@pytest.mark.parametrize(
    "coordinates",
    [
        [-181.0, 37.251, 7.2],
        [-121.642, 90.1, 7.2],
        [-121.642, 37.251, -100.1],
        [-121.642, 37.251, 1000.1],
        [-121.642, 37.251],
    ],
)
def test_invalid_geometry_coordinates_are_rejected(coordinates: list[float]) -> None:
    feature = usgs_feature(geometry={"type": "Point", "coordinates": coordinates})

    with pytest.raises(ExternalSourcePayloadError):
        fetch_events(usgs_response(features=[feature]))


@pytest.mark.parametrize("feature_id", ["", "   "])
def test_missing_or_blank_native_feature_id_is_rejected(feature_id: str) -> None:
    with pytest.raises(ExternalSourcePayloadError):
        fetch_events(usgs_response(features=[usgs_feature(id=feature_id)]))


def test_missing_required_properties_are_rejected() -> None:
    feature = usgs_feature()
    properties = cast(dict[str, object], feature["properties"])
    del properties["mag"]

    with pytest.raises(ExternalSourcePayloadError):
        fetch_events(usgs_response(features=[feature]))


def test_non_earthquake_feature_is_rejected() -> None:
    feature = usgs_feature()
    properties = cast(dict[str, object], feature["properties"])
    properties["type"] = "quarry blast"

    with pytest.raises(ExternalSourcePayloadError):
        fetch_events(usgs_response(features=[feature]))


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("tsunami", 2),
        ("sig", -1),
        ("status", "deleted"),
        ("place", "   "),
        ("magType", "   "),
    ],
)
def test_invalid_provider_properties_are_rejected(field: str, value: object) -> None:
    feature = usgs_feature()
    properties = cast(dict[str, object], feature["properties"])
    properties[field] = value

    with pytest.raises(ExternalSourcePayloadError):
        fetch_events(usgs_response(features=[feature]))


def test_epoch_milliseconds_become_aware_utc_event_and_update_times() -> None:
    event = first_event()

    assert event.event_time == datetime.fromtimestamp(1_787_688_000_000 / 1000, UTC)
    assert event.payload["source_updated_at"] == "2026-08-25T21:00:00Z"


def test_event_time_and_source_updated_at_remain_distinct() -> None:
    event = first_event()

    assert event.event_time.isoformat().replace("+00:00", "Z") != event.payload["source_updated_at"]


def test_later_updated_value_changes_payload_revision_but_not_identity() -> None:
    first = first_event()
    feature = usgs_feature()
    properties = cast(dict[str, object], feature["properties"])
    properties["updated"] = 1_787_695_200_000
    second = first_event(usgs_response(features=[feature]))

    assert first.source.source_event_id == second.source.source_event_id
    assert first.metadata.deduplication_key == second.metadata.deduplication_key
    assert first.payload["source_updated_at"] != second.payload["source_updated_at"]


def test_usgs_feature_id_is_used_directly_as_source_event_id() -> None:
    event = first_event()

    assert event.source.source_event_id == "us7000abcd"
    assert not event.source.source_event_id.startswith("usgs:")


def test_same_usgs_id_and_event_time_produce_same_deduplication_key() -> None:
    first = first_event()
    second = first_event()

    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_different_usgs_id_changes_deduplication_key() -> None:
    first = first_event()
    second = first_event(usgs_response(features=[usgs_feature(id="us7000efgh")]))

    assert first.metadata.deduplication_key != second.metadata.deduplication_key


def test_different_event_time_changes_deduplication_key() -> None:
    first = first_event()
    feature = usgs_feature()
    properties = cast(dict[str, object], feature["properties"])
    properties["time"] = 1_787_688_060_000
    second = first_event(usgs_response(features=[feature]))

    assert first.metadata.deduplication_key != second.metadata.deduplication_key


def test_changing_magnitude_does_not_change_source_event_id() -> None:
    first = first_event()
    feature = usgs_feature()
    properties = cast(dict[str, object], feature["properties"])
    properties["mag"] = 5.1
    second = first_event(usgs_response(features=[feature]))

    assert first.source.source_event_id == second.source.source_event_id


def test_changing_entity_or_correlation_does_not_change_source_event_id() -> None:
    first = first_event(entity=EntityReference(type="supplier", id="SUP-000001"))
    second = first_event(correlation_id="corr-seismic-002")

    assert first.source.source_event_id == second.source.source_event_id


def test_changing_event_id_does_not_change_deduplication_key() -> None:
    first = first_event()
    data = first.model_dump()
    data["event_id"] = uuid4()
    second = CanonicalEvent.model_validate(data)

    assert first.event_id != second.event_id
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_canonical_event_mapping_fields() -> None:
    entity = EntityReference(type="supplier", id="SUP-000001")
    event = first_event(entity=entity)

    assert event.event_type is EventType.SEISMIC_EVENT_DETECTED
    assert event.source.provider == "usgs"
    assert event.source.endpoint == USGS_QUERY_ENDPOINT
    assert "?" not in event.source.endpoint
    assert event.metadata.producer == "usgs-seismic-adapter"
    assert event.metadata.producer_version == "1.0.0"
    assert event.entity == entity
    assert event.location is None


def test_payload_validates_as_seismic_event_payload() -> None:
    event = first_event()

    payload = SeismicEventPayload.model_validate_json(json.dumps(event.payload))

    assert payload.magnitude == 4.6
    assert payload.tsunami is False
    assert payload.significance == 326
