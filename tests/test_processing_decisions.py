from __future__ import annotations

import re
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime, timedelta, timezone
from uuid import UUID, uuid4

import pytest

from supplychain.contracts import (
    CanonicalEvent,
    EntityReference,
    EventMetadata,
    EventType,
    LocationMetadata,
    SeismicEventPayload,
    SourceMetadata,
    generate_deduplication_key,
)
from supplychain.processing import (
    ProcessedEventRecord,
    ProcessingAssessment,
    ProcessingConsistencyError,
    ProcessingDecision,
    assess_event,
    generate_source_content_fingerprint,
)

DEFAULT_EVENT_ID = UUID("5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10")


def make_source(
    *,
    provider: str = "synthetic-weather",
    source_event_id: str = "weather-obs-001",
    request_id: str | None = "request-001",
) -> SourceMetadata:
    return SourceMetadata(
        provider=provider,
        endpoint="synthetic://source/reference",
        source_event_id=source_event_id,
        request_id=request_id,
    )


def make_event(
    *,
    event_id: UUID | None = DEFAULT_EVENT_ID,
    event_type: EventType = EventType.WEATHER_OBSERVATION_RECORDED,
    event_time: datetime = datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    ingested_at: datetime = datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
    source: SourceMetadata | None = None,
    entity: EntityReference | None = None,
    location: LocationMetadata | None = None,
    payload: dict[str, object] | None = None,
    correlation_id: str = "corr-processing-001",
    producer: str = "processing-test-producer",
    producer_version: str = "1.0.0",
    deduplication_key: str | None = None,
) -> CanonicalEvent:
    event_source = make_source() if source is None else source
    logical_key = deduplication_key or generate_deduplication_key(
        source=event_source,
        event_type=event_type,
        event_time=event_time,
    )
    event_data: dict[str, object] = {
        "event_type": event_type,
        "event_time": event_time,
        "ingested_at": ingested_at,
        "source": event_source,
        "entity": entity,
        "location": location,
        "payload": payload
        or {
            "temperature_2m_c": 21.2,
            "quality": {"flags": {"estimated": False, "source": "synthetic"}},
            "readings": [1, 2, 3],
        },
        "metadata": EventMetadata(
            correlation_id=correlation_id,
            producer=producer,
            producer_version=producer_version,
            deduplication_key=logical_key,
        ),
    }
    if event_id is not None:
        event_data["event_id"] = event_id
    return CanonicalEvent.model_validate(event_data)


def processed_record(event: CanonicalEvent) -> ProcessedEventRecord:
    return ProcessedEventRecord(
        deduplication_key=event.metadata.deduplication_key,
        source_content_fingerprint=generate_source_content_fingerprint(event),
    )


def with_payload(event: CanonicalEvent, payload: dict[str, object]) -> CanonicalEvent:
    data = event.model_dump()
    data["payload"] = payload
    return CanonicalEvent.model_validate(data)


def test_processing_public_api_imports() -> None:
    assert ProcessingDecision.NEW.value == "new"
    assert ProcessedEventRecord.__name__ == "ProcessedEventRecord"
    assert ProcessingAssessment.__name__ == "ProcessingAssessment"


def test_fingerprint_is_deterministic() -> None:
    assert generate_source_content_fingerprint(make_event()) == generate_source_content_fingerprint(
        make_event()
    )


def test_fingerprint_uses_sha256_prefixed_lowercase_hex_format() -> None:
    fingerprint = generate_source_content_fingerprint(make_event())

    assert re.fullmatch(r"sha256:[0-9a-f]{64}", fingerprint)


def test_repeated_fingerprint_generation_gives_same_result() -> None:
    event = make_event()

    assert generate_source_content_fingerprint(event) == generate_source_content_fingerprint(event)


def test_changing_event_id_does_not_change_fingerprint() -> None:
    first = make_event(event_id=uuid4())
    second = make_event(event_id=uuid4())

    assert first.event_id != second.event_id
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_ingested_at_does_not_change_fingerprint() -> None:
    first = make_event(ingested_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC))
    second = make_event(ingested_at=datetime(2026, 8, 26, 12, 1, tzinfo=UTC))

    assert first.ingested_at != second.ingested_at
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_correlation_id_does_not_change_fingerprint() -> None:
    first = make_event(correlation_id="corr-processing-001")
    second = make_event(correlation_id="corr-processing-999")

    assert first.metadata.correlation_id != second.metadata.correlation_id
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_request_id_does_not_change_fingerprint() -> None:
    first = make_event(source=make_source(request_id="request-001"))
    second = make_event(source=make_source(request_id="request-999"))

    assert first.source.request_id != second.source.request_id
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_entity_does_not_change_fingerprint() -> None:
    first = make_event(entity=None)
    second = make_event(entity=EntityReference(type="supplier", id="SUP-000001"))

    assert first.entity != second.entity
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_location_does_not_change_fingerprint() -> None:
    first = make_event(location=LocationMetadata(country_code="US", region="WA"))
    second = make_event(location=LocationMetadata(country_code="CA", region="BC"))

    assert first.location != second.location
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_producer_does_not_change_fingerprint() -> None:
    first = make_event(producer="processing-test-producer")
    second = make_event(producer="other-producer")

    assert first.metadata.producer != second.metadata.producer
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_changing_producer_version_does_not_change_fingerprint() -> None:
    first = make_event(producer_version="1.0.0")
    second = make_event(producer_version="2.0.0")

    assert first.metadata.producer_version != second.metadata.producer_version
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_equivalent_utc_instants_give_same_fingerprint() -> None:
    offset = timezone(timedelta(hours=-4))
    first = make_event(event_time=datetime(2026, 8, 25, 12, 0, tzinfo=UTC))
    second = make_event(event_time=datetime(2026, 8, 25, 8, 0, tzinfo=offset))

    assert first.event_time == second.event_time
    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_payload_top_level_key_ordering_does_not_change_fingerprint() -> None:
    first = make_event(payload={"b": 2, "a": 1})
    second = make_event(payload={"a": 1, "b": 2})

    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_nested_object_ordering_does_not_change_fingerprint() -> None:
    first = make_event(payload={"outer": {"b": 2, "a": {"y": 2, "x": 1}}})
    second = make_event(payload={"outer": {"a": {"x": 1, "y": 2}, "b": 2}})

    assert generate_source_content_fingerprint(first) == generate_source_content_fingerprint(second)


def test_array_ordering_changes_fingerprint() -> None:
    first = make_event(payload={"values": [1, 2, 3]})
    second = make_event(payload={"values": [3, 2, 1]})

    assert generate_source_content_fingerprint(first) != generate_source_content_fingerprint(second)


def test_payload_value_change_changes_fingerprint() -> None:
    first = make_event(payload={"temperature_2m_c": 21.2})
    second = make_event(payload={"temperature_2m_c": 22.0})

    assert first.metadata.deduplication_key == second.metadata.deduplication_key
    assert generate_source_content_fingerprint(first) != generate_source_content_fingerprint(second)


def test_event_type_change_changes_fingerprint() -> None:
    first = make_event(event_type=EventType.WEATHER_OBSERVATION_RECORDED)
    second = make_event(event_type=EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED)

    assert generate_source_content_fingerprint(first) != generate_source_content_fingerprint(second)


def test_source_provider_change_changes_fingerprint() -> None:
    first = make_event(source=make_source(provider="synthetic-weather"))
    second = make_event(source=make_source(provider="synthetic-weather-alt"))

    assert generate_source_content_fingerprint(first) != generate_source_content_fingerprint(second)


def test_source_event_id_change_changes_fingerprint() -> None:
    first = make_event(source=make_source(source_event_id="weather-obs-001"))
    second = make_event(source=make_source(source_event_id="weather-obs-002"))

    assert generate_source_content_fingerprint(first) != generate_source_content_fingerprint(second)


def test_event_time_change_changes_fingerprint() -> None:
    first = make_event(event_time=datetime(2026, 8, 25, 12, 0, tzinfo=UTC))
    second = make_event(event_time=datetime(2026, 8, 25, 12, 1, tzinfo=UTC))

    assert generate_source_content_fingerprint(first) != generate_source_content_fingerprint(second)


def test_no_previous_record_assesses_new() -> None:
    event = make_event()

    assessment = assess_event(event, None)

    assert assessment.decision is ProcessingDecision.NEW
    assert assessment.deduplication_key == event.metadata.deduplication_key
    assert assessment.previous_source_content_fingerprint is None


def test_same_logical_key_and_same_fingerprint_assesses_duplicate() -> None:
    event = make_event()

    assessment = assess_event(event, processed_record(event))

    assert assessment.decision is ProcessingDecision.DUPLICATE
    assert assessment.previous_source_content_fingerprint == assessment.source_content_fingerprint


def test_same_logical_key_and_different_fingerprint_assesses_revision_candidate() -> None:
    first = make_event(payload={"status": "nominal"})
    second = make_event(payload={"status": "delayed"})

    assessment = assess_event(second, processed_record(first))

    assert assessment.decision is ProcessingDecision.REVISION_CANDIDATE
    assert assessment.previous_source_content_fingerprint != assessment.source_content_fingerprint


def test_mismatching_prior_deduplication_key_fails_explicitly() -> None:
    event = make_event()
    previous = ProcessedEventRecord(
        deduplication_key="different-logical-event-key",
        source_content_fingerprint=generate_source_content_fingerprint(event),
    )

    with pytest.raises(ProcessingConsistencyError):
        assess_event(event, previous)


def test_inconsistent_event_deduplication_key_fails_explicitly() -> None:
    event = make_event(deduplication_key="incorrect-logical-key")

    with pytest.raises(ProcessingConsistencyError):
        assess_event(event, None)


def test_duplicate_events_may_have_different_event_id() -> None:
    first = make_event(event_id=uuid4())
    second = make_event(event_id=uuid4())

    assert first.event_id != second.event_id
    assert assess_event(second, processed_record(first)).decision is ProcessingDecision.DUPLICATE


def test_duplicate_events_may_have_different_ingested_at() -> None:
    first = make_event(ingested_at=datetime(2026, 8, 25, 12, 1, tzinfo=UTC))
    second = make_event(ingested_at=datetime(2026, 8, 25, 12, 2, tzinfo=UTC))

    assert first.ingested_at != second.ingested_at
    assert assess_event(second, processed_record(first)).decision is ProcessingDecision.DUPLICATE


def test_duplicate_events_may_have_different_correlation_id() -> None:
    first = make_event(correlation_id="corr-processing-001")
    second = make_event(correlation_id="corr-processing-002")

    assert first.metadata.correlation_id != second.metadata.correlation_id
    assert assess_event(second, processed_record(first)).decision is ProcessingDecision.DUPLICATE


def test_entity_enrichment_does_not_create_revision_candidate() -> None:
    first = make_event(entity=None)
    second = make_event(entity=EntityReference(type="supplier", id="SUP-000001"))

    assert assess_event(second, processed_record(first)).decision is ProcessingDecision.DUPLICATE


def test_usgs_changed_source_content_assesses_revision_candidate() -> None:
    source = make_source(provider="usgs", source_event_id="us7000abcd", request_id=None)
    event_time = datetime(2026, 8, 25, 20, 0, tzinfo=UTC)
    first_payload = SeismicEventPayload(
        latitude=37.251,
        longitude=-121.642,
        depth_km=7.2,
        magnitude=4.6,
        magnitude_type="mw",
        place="12 km E of Example, CA",
        status="reviewed",
        tsunami=False,
        significance=326,
        source_updated_at=datetime(2026, 8, 25, 21, 0, tzinfo=UTC),
    ).model_dump(mode="json")
    second_payload = SeismicEventPayload(
        latitude=37.251,
        longitude=-121.642,
        depth_km=7.2,
        magnitude=5.1,
        magnitude_type="mw",
        place="12 km E of Example, CA",
        status="reviewed",
        tsunami=False,
        significance=351,
        source_updated_at=datetime(2026, 8, 25, 22, 0, tzinfo=UTC),
    ).model_dump(mode="json")
    first = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=event_time,
        source=source,
        payload=first_payload,
    )
    second = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=event_time,
        source=source,
        payload=second_payload,
    )

    assert first.metadata.deduplication_key == second.metadata.deduplication_key
    assert assess_event(second, processed_record(first)).decision is (
        ProcessingDecision.REVISION_CANDIDATE
    )


def test_stage_10a_does_not_classify_newer_or_stale_revision() -> None:
    assert {decision.value for decision in ProcessingDecision} == {
        "new",
        "duplicate",
        "revision_candidate",
    }


def test_processing_value_objects_are_immutable() -> None:
    record = ProcessedEventRecord(
        deduplication_key="logical-key",
        source_content_fingerprint="sha256:" + "0" * 64,
    )
    field_name = "deduplication_key"

    with pytest.raises(FrozenInstanceError):
        setattr(record, field_name, "mutated")


def test_blank_prior_record_values_are_rejected_without_payload_context() -> None:
    with pytest.raises(ProcessingConsistencyError) as exc_info:
        ProcessedEventRecord(deduplication_key=" ", source_content_fingerprint="sha256:abc")

    assert "payload" not in str(exc_info.value).lower()
