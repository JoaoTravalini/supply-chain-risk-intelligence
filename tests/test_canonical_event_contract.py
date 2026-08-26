from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta, timezone
from pathlib import Path
from uuid import uuid4

import pytest
from pydantic import ValidationError

from supplychain.contracts import (
    CANONICAL_EVENT_SCHEMA_VERSION,
    CanonicalEvent,
    EntityReference,
    EventMetadata,
    EventType,
    LocationMetadata,
    SourceMetadata,
    generate_deduplication_key,
)

SCHEMA_PATH = Path("schemas/events/canonical-event-v1.schema.json")


def make_source(source_event_id: str = "weather-obs-001") -> SourceMetadata:
    return SourceMetadata(
        provider="synthetic-weather",
        endpoint="observations/daily",
        source_event_id=source_event_id,
        request_id="request-001",
    )


def make_entity(entity_id: str = "supplier-001") -> EntityReference:
    return EntityReference(type="supplier", id=entity_id)


def make_event(
    *,
    event_id: object | None = None,
    ingested_at: datetime | None = None,
    source: SourceMetadata | None = None,
    entity: EntityReference | None = None,
    event_time: datetime | None = None,
) -> CanonicalEvent:
    event_source = source or make_source()
    event_entity = entity or make_entity()
    occurred_at = event_time or datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    deduplication_key = generate_deduplication_key(
        source=event_source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=occurred_at,
    )
    event_data: dict[str, object] = {
        "event_type": EventType.WEATHER_OBSERVATION_RECORDED,
        "event_time": occurred_at,
        "source": event_source,
        "entity": event_entity,
        "location": LocationMetadata(country_code="US", region="WA"),
        "payload": {"temperature_c": 21.2, "observed": True},
        "metadata": EventMetadata(
            correlation_id="corr-001",
            producer="canonicalizer",
            producer_version="1.2.3",
            deduplication_key=deduplication_key,
        ),
    }
    if event_id is not None:
        event_data["event_id"] = event_id
    if ingested_at is not None:
        event_data["ingested_at"] = ingested_at
    return CanonicalEvent.model_validate(event_data)


def test_valid_event_construction() -> None:
    event = make_event()

    assert event.schema_version == CANONICAL_EVENT_SCHEMA_VERSION
    assert event.event_type is EventType.WEATHER_OBSERVATION_RECORDED
    assert event.source.provider == "synthetic-weather"
    assert event.entity is not None
    assert event.entity.id == "supplier-001"


def test_canonical_event_public_api() -> None:
    assert CanonicalEvent.__name__ == "CanonicalEvent"
    assert EventType.SEISMIC_EVENT_DETECTED.value == "seismic.event.detected"
    assert CANONICAL_EVENT_SCHEMA_VERSION == "1.0.0"


def test_unknown_field_rejection() -> None:
    with pytest.raises(ValidationError):
        CanonicalEvent.model_validate({**make_event().model_dump(), "unexpected": "nope"})


def test_invalid_event_type_rejection() -> None:
    data = make_event().model_dump()
    data["event_type"] = "weather.observation.changed"

    with pytest.raises(ValidationError):
        CanonicalEvent.model_validate(data)


def test_invalid_schema_version_rejection() -> None:
    data = make_event().model_dump()
    data["schema_version"] = "1.1.0"

    with pytest.raises(ValidationError):
        CanonicalEvent.model_validate(data)


def test_naive_event_time_rejection() -> None:
    data = make_event().model_dump()
    data["event_time"] = datetime(2026, 8, 25, 12, 0)

    with pytest.raises(ValidationError):
        CanonicalEvent.model_validate(data)


def test_naive_ingested_at_rejection() -> None:
    with pytest.raises(ValidationError):
        make_event(ingested_at=datetime(2026, 8, 25, 12, 1))


def test_aware_non_utc_timestamps_normalize_to_utc() -> None:
    offset = timezone(timedelta(hours=-4))
    event = make_event(
        event_time=datetime(2026, 8, 25, 8, 0, tzinfo=offset),
        ingested_at=datetime(2026, 8, 25, 8, 5, tzinfo=offset),
    )

    assert event.event_time == datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    assert event.ingested_at == datetime(2026, 8, 25, 12, 5, tzinfo=UTC)


def test_invalid_country_code_rejection() -> None:
    with pytest.raises(ValidationError):
        LocationMetadata(country_code="usa")


def test_empty_required_source_provider_rejection() -> None:
    with pytest.raises(ValidationError):
        SourceMetadata(provider="   ", source_event_id="weather-obs-001")


def test_missing_source_event_id_rejection() -> None:
    with pytest.raises(ValidationError):
        SourceMetadata.model_validate({"provider": "synthetic-weather"})


def test_empty_source_event_id_rejection() -> None:
    with pytest.raises(ValidationError):
        SourceMetadata(provider="synthetic-weather", source_event_id="")


def test_whitespace_only_source_event_id_rejection() -> None:
    with pytest.raises(ValidationError):
        SourceMetadata(provider="synthetic-weather", source_event_id="   ")


def test_invalid_producer_version_rejection() -> None:
    with pytest.raises(ValidationError):
        EventMetadata(
            correlation_id="corr-001",
            producer="canonicalizer",
            producer_version="v1",
            deduplication_key="dedup-001",
        )


def test_immutability_after_validation() -> None:
    event = make_event()

    with pytest.raises(ValidationError):
        event.payload = {"mutated": True}


def test_same_logical_event_identity_creates_same_deduplication_key() -> None:
    source = make_source()
    event_time = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    first = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )
    second = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )

    assert first == second


def test_different_source_event_id_changes_deduplication_key() -> None:
    event_time = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    first = generate_deduplication_key(
        source=make_source("weather-obs-001"),
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )
    second = generate_deduplication_key(
        source=make_source("weather-obs-002"),
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )

    assert first != second


def test_different_provider_changes_deduplication_key() -> None:
    event_time = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    first_source = make_source()
    second_source = SourceMetadata(
        provider="synthetic-weather-alt",
        endpoint="observations/daily",
        source_event_id="weather-obs-001",
        request_id="request-001",
    )

    first = generate_deduplication_key(
        source=first_source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )
    second = generate_deduplication_key(
        source=second_source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )

    assert first != second


def test_different_event_type_changes_deduplication_key() -> None:
    source = make_source()
    event_time = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)

    first = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=event_time,
    )
    second = generate_deduplication_key(
        source=source,
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=event_time,
    )

    assert first != second


def test_different_event_time_changes_deduplication_key() -> None:
    source = make_source()

    first = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    )
    second = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
    )

    assert first != second


def test_changing_event_id_does_not_change_logical_deduplication_identity() -> None:
    first = make_event(event_id=uuid4())
    second = make_event(event_id=uuid4())

    assert first.event_id != second.event_id
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_ingested_at_does_not_change_logical_deduplication_identity() -> None:
    first = make_event(ingested_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC))
    second = make_event(ingested_at=datetime(2026, 8, 26, 12, 1, tzinfo=UTC))

    assert first.ingested_at != second.ingested_at
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_request_id_does_not_change_logical_deduplication_identity() -> None:
    first_source = make_source()
    second_source = SourceMetadata(
        provider="synthetic-weather",
        endpoint="observations/daily",
        source_event_id="weather-obs-001",
        request_id="request-999",
    )

    first = make_event(source=first_source)
    second = make_event(source=second_source)

    assert first.source.request_id != second.source.request_id
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_correlation_id_does_not_change_logical_deduplication_identity() -> None:
    first = make_event()
    data = first.model_dump()
    data["metadata"] = {
        **first.metadata.model_dump(),
        "correlation_id": "corr-999",
    }
    second = CanonicalEvent.model_validate(data)

    assert first.metadata.correlation_id != second.metadata.correlation_id
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_entity_does_not_change_logical_deduplication_identity() -> None:
    first = make_event(entity=None)
    second = make_event(entity=make_entity("supplier-999"))

    assert first.entity != second.entity
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_location_does_not_change_logical_deduplication_identity() -> None:
    first = make_event()
    data = first.model_dump()
    data["location"] = {"country_code": "CA", "region": "BC"}
    second = CanonicalEvent.model_validate(data)

    assert first.location != second.location
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_changing_payload_does_not_change_logical_deduplication_identity() -> None:
    first = make_event()
    data = first.model_dump()
    data["payload"] = {"temperature_c": 19.8, "observed": True}
    second = CanonicalEvent.model_validate(data)

    assert first.payload != second.payload
    assert first.metadata.deduplication_key == second.metadata.deduplication_key


def test_equivalent_aware_timestamps_produce_same_deduplication_key() -> None:
    source = make_source()
    first_time = datetime(2026, 8, 25, 12, 0, tzinfo=UTC)
    second_time = datetime(2026, 8, 25, 8, 0, tzinfo=timezone(timedelta(hours=-4)))

    first = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=first_time,
    )
    second = generate_deduplication_key(
        source=source,
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=second_time,
    )

    assert first == second


def test_committed_json_schema_matches_model() -> None:
    generated_schema = CanonicalEvent.model_json_schema()
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == generated_schema
