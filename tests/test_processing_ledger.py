from __future__ import annotations

import re
import shutil
import sqlite3
from collections.abc import Iterator
from contextlib import closing, suppress
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from supplychain.contracts import (
    CanonicalEvent,
    EventMetadata,
    EventType,
    SeismicEventPayload,
    SourceMetadata,
    generate_deduplication_key,
)
from supplychain.processing import (
    PROCESSED_EVENTS_TABLE,
    SQLITE_LEDGER_SCHEMA_VERSION,
    ProcessingConsistencyError,
    ProcessingResolution,
    SqliteProcessingLedger,
    extract_source_revision,
    generate_source_content_fingerprint,
)

DEFAULT_EVENT_ID = UUID("5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10")


@pytest.fixture
def ledger_tmp_path(request: pytest.FixtureRequest) -> Iterator[Path]:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    root = Path(".pytest-ledger-tests")
    path = root / safe_name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        with suppress(OSError):
            root.rmdir()


def make_source(
    *,
    provider: str = "synthetic-weather",
    source_event_id: str = "weather-obs-001",
) -> SourceMetadata:
    return SourceMetadata(
        provider=provider,
        endpoint="synthetic://source/reference",
        source_event_id=source_event_id,
    )


def make_event(
    *,
    event_id: UUID = DEFAULT_EVENT_ID,
    event_type: EventType = EventType.WEATHER_OBSERVATION_RECORDED,
    event_time: datetime = datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    source: SourceMetadata | None = None,
    payload: dict[str, object] | None = None,
    producer: str = "ledger-test-producer",
) -> CanonicalEvent:
    event_source = make_source() if source is None else source
    event_data: dict[str, object] = {
        "event_id": event_id,
        "event_type": event_type,
        "event_time": event_time,
        "ingested_at": datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
        "source": event_source,
        "payload": payload or {"temperature_2m_c": 21.2, "observed": True},
        "metadata": EventMetadata(
            correlation_id="corr-ledger-001",
            producer=producer,
            producer_version="1.0.0",
            deduplication_key=generate_deduplication_key(
                source=event_source,
                event_type=event_type,
                event_time=event_time,
            ),
        ),
    }
    return CanonicalEvent.model_validate(event_data)


def make_usgs_event(
    *,
    event_id: UUID = DEFAULT_EVENT_ID,
    source_updated_at: datetime,
    magnitude: float,
    significance: int = 326,
) -> CanonicalEvent:
    source = make_source(provider="usgs", source_event_id="us7000abcd")
    payload = SeismicEventPayload(
        latitude=37.251,
        longitude=-121.642,
        depth_km=7.2,
        magnitude=magnitude,
        magnitude_type="mw",
        place="12 km E of Example, CA",
        status="reviewed",
        tsunami=False,
        significance=significance,
        source_updated_at=source_updated_at,
    ).model_dump(mode="json")
    return make_event(
        event_id=event_id,
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=datetime(2026, 8, 25, 20, 0, tzinfo=UTC),
        source=source,
        payload=payload,
        producer="usgs-seismic-adapter",
    )


def row_count(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("SELECT COUNT(*) FROM processed_events").fetchone()[0])


def table_columns(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        return {str(row[1]) for row in connection.execute("PRAGMA table_info(processed_events)")}


def user_version(path: Path) -> int:
    with closing(sqlite3.connect(path)) as connection:
        return int(connection.execute("PRAGMA user_version").fetchone()[0])


def test_new_sqlite_ledger_initializes_schema_version_1(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"

    with SqliteProcessingLedger(path):
        pass

    assert user_version(path) == SQLITE_LEDGER_SCHEMA_VERSION
    assert PROCESSED_EVENTS_TABLE in table_names(path)


def test_reopening_schema_version_1_succeeds(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"

    SqliteProcessingLedger(path).close()

    with SqliteProcessingLedger(path) as ledger:
        assert ledger.get_record("missing-key") is None


def test_unsupported_schema_version_fails_explicitly(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    with closing(sqlite3.connect(path)) as connection:
        connection.execute("PRAGMA user_version = 99")
        connection.commit()

    with pytest.raises(ProcessingConsistencyError):
        SqliteProcessingLedger(path)


def test_assess_on_empty_ledger_returns_new(ledger_tmp_path: Path) -> None:
    event = make_event()

    with SqliteProcessingLedger(ledger_tmp_path / "processing-ledger.sqlite") as ledger:
        result = ledger.assess(event)

    assert result.resolution is ProcessingResolution.NEW
    assert result.deduplication_key == event.metadata.deduplication_key


def test_assess_new_does_not_write_row(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event()

    with SqliteProcessingLedger(path) as ledger:
        ledger.assess(event)

    assert row_count(path) == 0


def test_record_success_new_inserts_one_row(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event()

    with SqliteProcessingLedger(path) as ledger:
        result = ledger.record_success(event)

    assert result.resolution is ProcessingResolution.NEW
    assert row_count(path) == 1


def test_record_survives_connection_close_and_reopen(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event()

    with SqliteProcessingLedger(path) as first:
        first.record_success(event)
    with SqliteProcessingLedger(path) as second:
        record = second.get_record(event.metadata.deduplication_key)

    assert record is not None
    assert record.source_content_fingerprint == generate_source_content_fingerprint(event)


def test_record_fields_round_trip_correctly(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(event)
        record = ledger.get_record(event.metadata.deduplication_key)

    assert record is not None
    assert record.deduplication_key == event.metadata.deduplication_key
    assert record.source_content_fingerprint == generate_source_content_fingerprint(event)
    assert record.source_revision_at == datetime(2026, 8, 25, 15, 0, tzinfo=UTC)
    assert record.canonical_event_id == event.event_id
    assert record.event_type is EventType.SEISMIC_EVENT_DETECTED
    assert record.source_provider == "usgs"
    assert record.source_event_id == "us7000abcd"
    assert record.event_time == event.event_time
    assert record.schema_version == event.schema_version


def test_exact_duplicate_assesses_duplicate(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event()

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(event)
        result = ledger.assess(make_event(event_id=uuid4()))

    assert result.resolution is ProcessingResolution.DUPLICATE


def test_duplicate_record_success_is_idempotent_noop(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event()
    duplicate = make_event(event_id=uuid4())

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(event)
        result = ledger.record_success(duplicate)
        record = ledger.get_record(event.metadata.deduplication_key)

    assert result.resolution is ProcessingResolution.DUPLICATE
    assert row_count(path) == 1
    assert record is not None
    assert record.canonical_event_id == event.event_id


def test_usgs_newer_revision_assesses_newer_revision(ledger_tmp_path: Path) -> None:
    stored = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )
    incoming = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 7, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )

    with SqliteProcessingLedger(ledger_tmp_path / "processing-ledger.sqlite") as ledger:
        ledger.record_success(stored)
        result = ledger.assess(incoming)

    assert result.resolution is ProcessingResolution.NEWER_REVISION
    assert result.previous_source_revision_at == datetime(2026, 8, 25, 15, 0, tzinfo=UTC)
    assert result.incoming_source_revision_at == datetime(2026, 8, 25, 15, 7, tzinfo=UTC)


def test_record_success_newer_revision_updates_persisted_state(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    stored = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )
    incoming = make_usgs_event(
        event_id=uuid4(),
        source_updated_at=datetime(2026, 8, 25, 15, 7, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(stored)
        result = ledger.record_success(incoming)
        record = ledger.get_record(stored.metadata.deduplication_key)

    assert result.resolution is ProcessingResolution.NEWER_REVISION
    assert record is not None
    assert record.source_content_fingerprint == generate_source_content_fingerprint(incoming)
    assert record.source_revision_at == datetime(2026, 8, 25, 15, 7, tzinfo=UTC)
    assert record.canonical_event_id == incoming.event_id


def test_older_usgs_revision_assesses_stale_revision(ledger_tmp_path: Path) -> None:
    latest = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 7, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )
    older = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )

    with SqliteProcessingLedger(ledger_tmp_path / "processing-ledger.sqlite") as ledger:
        ledger.record_success(latest)
        result = ledger.assess(older)

    assert result.resolution is ProcessingResolution.STALE_REVISION


def test_record_success_stale_revision_does_not_regress_state(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    latest = make_usgs_event(
        event_id=uuid4(),
        source_updated_at=datetime(2026, 8, 25, 15, 7, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )
    older = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(latest)
        result = ledger.record_success(older)
        record = ledger.get_record(latest.metadata.deduplication_key)

    assert result.resolution is ProcessingResolution.STALE_REVISION
    assert record is not None
    assert record.source_content_fingerprint == generate_source_content_fingerprint(latest)
    assert record.canonical_event_id == latest.event_id


def test_equal_source_revision_timestamp_changed_content_conflicts(ledger_tmp_path: Path) -> None:
    first = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )
    second = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )

    with SqliteProcessingLedger(ledger_tmp_path / "processing-ledger.sqlite") as ledger:
        ledger.record_success(first)
        result = ledger.assess(second)

    assert result.resolution is ProcessingResolution.REVISION_CONFLICT


def test_conflict_record_success_does_not_mutate_persisted_row(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    first = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )
    second = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(first)
        result = ledger.record_success(second)
        record = ledger.get_record(first.metadata.deduplication_key)

    assert result.resolution is ProcessingResolution.REVISION_CONFLICT
    assert record is not None
    assert record.source_content_fingerprint == generate_source_content_fingerprint(first)


def test_changed_content_without_comparable_revision_conflicts(ledger_tmp_path: Path) -> None:
    first = make_event(payload={"temperature_2m_c": 21.2})
    second = make_event(payload={"temperature_2m_c": 22.0})

    with SqliteProcessingLedger(ledger_tmp_path / "processing-ledger.sqlite") as ledger:
        ledger.record_success(first)
        result = ledger.assess(second)

    assert result.resolution is ProcessingResolution.REVISION_CONFLICT
    assert result.incoming_source_revision_at is None
    assert result.previous_source_revision_at is None


def test_incoming_revision_marker_remains_utc_aware_after_persistence_round_trip(
    ledger_tmp_path: Path,
) -> None:
    event = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )

    with SqliteProcessingLedger(ledger_tmp_path / "processing-ledger.sqlite") as ledger:
        ledger.record_success(event)
        record = ledger.get_record(event.metadata.deduplication_key)

    assert record is not None
    assert record.source_revision_at is not None
    assert record.source_revision_at.tzinfo is UTC


def test_event_id_is_audit_metadata_not_primary_key(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    first = make_event(event_id=uuid4())
    duplicate = make_event(event_id=uuid4())

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(first)
        ledger.record_success(duplicate)
        record = ledger.get_record(first.metadata.deduplication_key)

    assert row_count(path) == 1
    assert record is not None
    assert record.canonical_event_id == first.event_id


def test_deduplication_key_is_primary_logical_key(ledger_tmp_path: Path) -> None:
    columns = table_info_after_init(ledger_tmp_path / "processing-ledger.sqlite")
    primary_key_columns = {str(row[1]) for row in columns if int(row[5]) == 1}

    assert primary_key_columns == {"deduplication_key"}


def test_no_full_payload_or_event_json_is_persisted(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    SqliteProcessingLedger(path).close()

    columns = table_columns(path)

    assert "payload" not in columns
    assert "event" not in columns
    assert "canonical_event" not in columns
    assert "canonical_event_json" not in columns


def test_parameterized_persistence_handles_synthetic_source_identifiers(
    ledger_tmp_path: Path,
) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event(
        source=make_source(
            provider="synthetic-provider",
            source_event_id="synthetic'; DROP TABLE processed_events; --",
        )
    )

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(event)

    assert row_count(path) == 1
    assert PROCESSED_EVENTS_TABLE in table_names(path)


def test_newer_then_older_out_of_order_success_cannot_regress_state(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    first = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )
    latest = make_usgs_event(
        event_id=uuid4(),
        source_updated_at=datetime(2026, 8, 25, 15, 7, tzinfo=UTC),
        magnitude=5.1,
        significance=351,
    )
    older = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )

    with SqliteProcessingLedger(path) as ledger:
        ledger.record_success(first)
        ledger.record_success(latest)
        result = ledger.record_success(older)
        record = ledger.get_record(first.metadata.deduplication_key)

    assert result.resolution is ProcessingResolution.STALE_REVISION
    assert record is not None
    assert record.source_revision_at == datetime(2026, 8, 25, 15, 7, tzinfo=UTC)
    assert record.source_content_fingerprint == generate_source_content_fingerprint(latest)


def test_two_ledger_instances_observe_persisted_successful_state(ledger_tmp_path: Path) -> None:
    path = ledger_tmp_path / "processing-ledger.sqlite"
    event = make_event()
    first = SqliteProcessingLedger(path)
    second = SqliteProcessingLedger(path)
    try:
        first.record_success(event)

        assert second.assess(make_event(event_id=uuid4())).resolution is (
            ProcessingResolution.DUPLICATE
        )
    finally:
        first.close()
        second.close()


def test_source_revision_extraction_is_explicit_to_usgs_seismic_events() -> None:
    usgs_event = make_usgs_event(
        source_updated_at=datetime(2026, 8, 25, 15, 0, tzinfo=UTC),
        magnitude=4.6,
    )
    weather_event = make_event(payload={"source_updated_at": "2026-08-25T15:00:00Z"})

    usgs_revision = extract_source_revision(usgs_event)

    assert usgs_revision is not None
    assert usgs_revision.source_revision_at == datetime(2026, 8, 25, 15, 0, tzinfo=UTC)
    assert extract_source_revision(weather_event) is None


def table_names(path: Path) -> set[str]:
    with closing(sqlite3.connect(path)) as connection:
        return {
            str(row[0])
            for row in connection.execute("SELECT name FROM sqlite_master WHERE type = 'table'")
        }


def table_info_after_init(path: Path) -> list[sqlite3.Row]:
    ledger = SqliteProcessingLedger(path)
    ledger.close()
    with closing(sqlite3.connect(path)) as connection:
        connection.row_factory = sqlite3.Row
        return list(connection.execute("PRAGMA table_info(processed_events)"))
