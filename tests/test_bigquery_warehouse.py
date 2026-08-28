from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, cast
from uuid import UUID

import pytest
from google.api_core.exceptions import GoogleAPICallError
from pydantic import JsonValue

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
from supplychain.domain import Criticality, Supplier, SupplierCategory, SupplierLocation
from supplychain.processing.fingerprints import generate_source_content_fingerprint
from supplychain.warehouse import (
    BigQueryCanonicalEventHandler,
    BigQueryRawEventSink,
    BigQuerySupplierSnapshotLoader,
    BigQueryWarehouseConfig,
    WarehouseConfigurationError,
    WarehouseJobTimeoutError,
    WarehouseWriteError,
    canonical_event_to_raw_row,
    supplier_to_core_row,
)

REPO_ROOT = Path(__file__).resolve().parents[1]
RAW_SCHEMA_PATH = REPO_ROOT / "infra" / "schemas" / "bigquery" / "raw" / "canonical_events.json"
SUPPLIERS_SCHEMA_PATH = REPO_ROOT / "infra" / "schemas" / "bigquery" / "core" / "suppliers.json"
CORE_SQL_PATH = REPO_ROOT / "infra" / "sql" / "core" / "canonical_events.sql"
DEFAULT_EVENT_ID = UUID("5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10")
DEFAULT_USGS_EVENT_ID = UUID("136f45ac-8bb8-43de-82f9-fb392ac49d28")


class FakeLoadJob:
    def __init__(
        self,
        *,
        job_id: str = "job-001",
        failure: Exception | None = None,
    ) -> None:
        self.job_id = job_id
        self.failure = failure
        self.result_timeouts: list[float | None] = []

    def result(self, timeout: float | None = None) -> object:
        self.result_timeouts.append(timeout)
        if self.failure is not None:
            raise self.failure
        return object()


class FakeBigQueryClient:
    def __init__(self, *, job: FakeLoadJob | None = None) -> None:
        self.job = FakeLoadJob() if job is None else job
        self.load_table_from_json_calls: list[tuple[Sequence[Mapping[str, Any]], str, Any]] = []
        self.insert_rows_json_calls: list[object] = []
        self.closed = False

    def load_table_from_json(
        self,
        json_rows: Sequence[Mapping[str, Any]],
        destination: str,
        *,
        job_config: object,
    ) -> FakeLoadJob:
        self.load_table_from_json_calls.append((json_rows, destination, job_config))
        return self.job

    def insert_rows_json(self, *args: object, **kwargs: object) -> object:
        self.insert_rows_json_calls.append((args, kwargs))
        raise AssertionError("streaming inserts must not be used")

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True, slots=True)
class RawSelectionRow:
    event_id: str
    deduplication_key: str
    source_content_fingerprint: str
    source_revision_at: datetime | None
    ingested_at: datetime


def make_event(
    *,
    event_id: UUID = DEFAULT_EVENT_ID,
    event_type: EventType = EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED,
    source: SourceMetadata | None = None,
    event_time: datetime = datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    ingested_at: datetime = datetime(2026, 8, 28, 12, 1, tzinfo=UTC),
    payload: dict[str, JsonValue] | None = None,
) -> CanonicalEvent:
    event_source = (
        SourceMetadata(
            provider="synthetic-operational",
            endpoint="synthetic://warehouse",
            source_event_id="warehouse-event-001",
            request_id="request-warehouse-001",
        )
        if source is None
        else source
    )
    event_payload: dict[str, JsonValue] = (
        {"status": "nominal", "on_time_delivery_pct": 98.5} if payload is None else payload
    )
    return CanonicalEvent(
        event_id=event_id,
        event_type=event_type,
        event_time=event_time,
        ingested_at=ingested_at,
        source=event_source,
        entity=EntityReference(type="supplier", id="SUP-000001"),
        location=LocationMetadata(country_code="US", region="WA"),
        payload=event_payload,
        metadata=EventMetadata(
            correlation_id="corr-warehouse-001",
            producer="warehouse-test",
            producer_version="1.0.0",
            deduplication_key=generate_deduplication_key(
                source=event_source,
                event_type=event_type,
                event_time=event_time,
            ),
        ),
    )


def make_usgs_event(
    *,
    event_id: UUID = DEFAULT_USGS_EVENT_ID,
    source_updated_at: datetime = datetime(2026, 8, 28, 13, 0, tzinfo=UTC),
) -> CanonicalEvent:
    source = SourceMetadata(
        provider="usgs",
        endpoint="https://earthquake.usgs.gov/fdsnws/event/1/query",
        source_event_id="usgs-feature-001",
        request_id="request-usgs-001",
    )
    payload = SeismicEventPayload(
        latitude=37.25,
        longitude=-122.1,
        depth_km=8.4,
        magnitude=4.2,
        magnitude_type="mw",
        place="10 km W of Synthetic City",
        status="reviewed",
        tsunami=False,
        significance=320,
        source_updated_at=source_updated_at,
    ).model_dump(mode="json")
    return make_event(
        event_id=event_id,
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        source=source,
        event_time=datetime(2026, 8, 28, 12, 30, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 28, 13, 2, tzinfo=UTC),
        payload=payload,
    )


def make_supplier() -> Supplier:
    return Supplier(
        supplier_id="SUP-000001",
        name="Synthetic Components North",
        category=SupplierCategory.ELECTRONIC_COMPONENTS,
        criticality=Criticality.HIGH,
        location=SupplierLocation(
            country_code="US",
            region="WA",
            city="Seattle",
            latitude=47.6062,
            longitude=-122.3321,
        ),
        annual_spend_usd=1_250_000,
        typical_lead_time_days=28,
        dependency_score=0.74,
        single_source=True,
    )


def load_schema(path: Path) -> dict[str, dict[str, str]]:
    fields = json.loads(path.read_text(encoding="utf-8"))
    return {str(field["name"]): field for field in fields}


def select_authoritative_current(rows: Sequence[RawSelectionRow]) -> tuple[RawSelectionRow, ...]:
    selected: list[RawSelectionRow] = []
    keys = sorted({row.deduplication_key for row in rows})
    for key in keys:
        key_rows = [row for row in rows if row.deduplication_key == key]
        has_revision = any(row.source_revision_at is not None for row in key_rows)
        has_unversioned = any(row.source_revision_at is None for row in key_rows)
        if has_revision and has_unversioned:
            continue
        if has_unversioned:
            fingerprints = {row.source_content_fingerprint for row in key_rows}
            if len(fingerprints) != 1:
                continue
            selected.append(sorted(key_rows, key=lambda row: (row.ingested_at, row.event_id))[0])
            continue
        revision_values = [cast(datetime, row.source_revision_at) for row in key_rows]
        latest_revision = max(revision_values)
        top_rows = [row for row in key_rows if row.source_revision_at == latest_revision]
        top_fingerprints = {row.source_content_fingerprint for row in top_rows}
        if len(top_fingerprints) != 1:
            continue
        selected.append(sorted(top_rows, key=lambda row: (row.ingested_at, row.event_id))[0])
    return tuple(selected)


def row(
    *,
    event_id: str,
    key: str = "dedup-1",
    fingerprint: str = "sha256:aaa",
    revision: datetime | None = None,
    ingested_at: datetime = datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
) -> RawSelectionRow:
    return RawSelectionRow(
        event_id=event_id,
        deduplication_key=key,
        source_content_fingerprint=fingerprint,
        source_revision_at=revision,
        ingested_at=ingested_at,
    )


def test_raw_schema_contains_required_canonical_fields() -> None:
    schema = load_schema(RAW_SCHEMA_PATH)

    assert schema["event_id"]["type"] == "STRING"
    assert schema["event_id"]["mode"] == "REQUIRED"
    assert schema["event_type"]["mode"] == "REQUIRED"
    assert schema["schema_version"]["mode"] == "REQUIRED"
    assert schema["event_time"]["type"] == "TIMESTAMP"
    assert schema["ingested_at"]["type"] == "TIMESTAMP"
    assert schema["source_provider"]["mode"] == "REQUIRED"
    assert schema["source_event_id"]["mode"] == "REQUIRED"
    assert schema["deduplication_key"]["mode"] == "REQUIRED"
    assert schema["source_content_fingerprint"]["mode"] == "REQUIRED"
    assert schema["source_revision_at"] == {
        "name": "source_revision_at",
        "type": "TIMESTAMP",
        "mode": "NULLABLE",
        "description": "Comparable source revision timestamp where explicitly supported.",
    }
    assert schema["payload"]["type"] == "JSON"
    assert schema["payload"]["mode"] == "REQUIRED"


def test_raw_schema_excludes_transport_retry_and_dlq_state() -> None:
    schema = load_schema(RAW_SCHEMA_PATH)

    assert "ack_id" not in schema
    assert "delivery_attempt" not in schema
    assert "retry_counter" not in schema
    assert "retry_count" not in schema
    assert "dlq_state" not in schema
    assert "message_id" not in schema


def test_supplier_schema_aligns_with_supplier_contract() -> None:
    schema = load_schema(SUPPLIERS_SCHEMA_PATH)

    assert set(schema) == {
        "schema_version",
        "supplier_id",
        "name",
        "category",
        "criticality",
        "country_code",
        "region",
        "city",
        "latitude",
        "longitude",
        "annual_spend_usd",
        "typical_lead_time_days",
        "dependency_score",
        "single_source",
    }
    assert schema["supplier_id"]["type"] == "STRING"
    assert schema["annual_spend_usd"]["type"] == "INTEGER"
    assert schema["dependency_score"]["type"] == "FLOAT"
    assert schema["single_source"]["type"] == "BOOLEAN"
    assert all(field["mode"] == "REQUIRED" for field in schema.values())


def test_core_sql_uses_revision_safe_conflict_exclusion() -> None:
    sql = CORE_SQL_PATH.read_text(encoding="utf-8")

    assert "COUNT(DISTINCT source_content_fingerprint)" in sql
    assert "ROW_NUMBER()" in sql
    assert "key_integrity.revisioned_rows = 0" in sql
    assert "key_integrity.null_revision_rows = 0" in sql
    assert "top_revision_fingerprint_count = 1" in sql
    assert "ORDER BY ingested_at ASC, event_id ASC" in sql
    assert "ORDER BY ingested_at DESC" not in sql


def test_core_reference_collapses_duplicate_same_fingerprint() -> None:
    first = row(event_id="event-1", ingested_at=datetime(2026, 8, 28, 12, 0, tzinfo=UTC))
    duplicate = row(event_id="event-2", ingested_at=datetime(2026, 8, 28, 12, 1, tzinfo=UTC))

    assert select_authoritative_current([duplicate, first]) == (first,)


def test_core_reference_selects_greatest_source_revision() -> None:
    old = row(event_id="event-old", revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC))
    new = row(
        event_id="event-new",
        fingerprint="sha256:bbb",
        revision=datetime(2026, 8, 28, 13, 0, tzinfo=UTC),
    )

    assert select_authoritative_current([new, old]) == (new,)


def test_core_reference_excludes_stale_revision_from_current() -> None:
    old = row(event_id="event-old", revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC))
    new = row(
        event_id="event-new",
        fingerprint="sha256:bbb",
        revision=datetime(2026, 8, 28, 13, 0, tzinfo=UTC),
    )

    selected = select_authoritative_current([old, new])

    assert old not in selected
    assert selected == (new,)


def test_core_reference_excludes_equal_revision_fingerprint_conflict() -> None:
    revision = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)
    first = row(event_id="event-1", fingerprint="sha256:aaa", revision=revision)
    second = row(event_id="event-2", fingerprint="sha256:bbb", revision=revision)

    assert select_authoritative_current([first, second]) == ()


def test_core_reference_excludes_unversioned_fingerprint_conflict() -> None:
    first = row(event_id="event-1", fingerprint="sha256:aaa")
    second = row(event_id="event-2", fingerprint="sha256:bbb")

    assert select_authoritative_current([first, second]) == ()


def test_core_reference_excludes_mixed_revision_marker_state() -> None:
    unversioned = row(event_id="event-1")
    revisioned = row(event_id="event-2", revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC))

    assert select_authoritative_current([unversioned, revisioned]) == ()


def test_core_reference_uses_deterministic_duplicate_representative() -> None:
    later_event_id = row(
        event_id="event-b",
        revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 28, 12, 5, tzinfo=UTC),
    )
    earlier_event_id = row(
        event_id="event-a",
        revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
        ingested_at=datetime(2026, 8, 28, 12, 5, tzinfo=UTC),
    )

    assert select_authoritative_current([later_event_id, earlier_event_id]) == (earlier_event_id,)


def test_raw_row_mapping_preserves_canonical_event_fields() -> None:
    event = make_event()

    raw = canonical_event_to_raw_row(event)

    assert raw["event_id"] == str(event.event_id)
    assert raw["event_type"] == "supplier.operational.snapshot.recorded"
    assert raw["schema_version"] == "1.0.0"
    assert raw["event_time"] == "2026-08-28T12:00:00Z"
    assert raw["ingested_at"] == "2026-08-28T12:01:00Z"
    assert raw["source_provider"] == "synthetic-operational"
    assert raw["source_endpoint"] == "synthetic://warehouse"
    assert raw["source_event_id"] == "warehouse-event-001"
    assert raw["source_request_id"] == "request-warehouse-001"
    assert raw["entity_type"] == "supplier"
    assert raw["entity_id"] == "SUP-000001"
    assert raw["location_country_code"] == "US"
    assert raw["location_region"] == "WA"
    assert raw["correlation_id"] == "corr-warehouse-001"
    assert raw["producer"] == "warehouse-test"
    assert raw["producer_version"] == "1.0.0"
    assert raw["deduplication_key"] == event.metadata.deduplication_key


def test_raw_row_mapping_reuses_source_content_fingerprint() -> None:
    event = make_event()

    assert canonical_event_to_raw_row(event)[
        "source_content_fingerprint"
    ] == generate_source_content_fingerprint(event)


def test_raw_row_mapping_extracts_usgs_revision_only() -> None:
    usgs = make_usgs_event(source_updated_at=datetime(2026, 8, 28, 13, 4, tzinfo=UTC))
    operational = make_event(payload={"source_updated_at": "2026-08-28T99:99:99Z"})

    assert canonical_event_to_raw_row(usgs)["source_revision_at"] == "2026-08-28T13:04:00Z"
    assert canonical_event_to_raw_row(operational)["source_revision_at"] is None


def test_raw_row_mapping_preserves_json_payload_without_mutating_event() -> None:
    event = make_event(payload={"nested": {"ok": True}, "values": [1, 2, 3]})
    before = event.model_dump(mode="json")

    raw = canonical_event_to_raw_row(event)

    assert raw["payload"] == {"nested": {"ok": True}, "values": [1, 2, 3]}
    assert event.model_dump(mode="json") == before


def test_raw_sink_uses_batch_load_job_write_append_and_finite_timeout() -> None:
    client = FakeBigQueryClient()
    config = BigQueryWarehouseConfig(project_id="supplychain-local", job_timeout_seconds=12.5)
    event = make_event()

    result = BigQueryRawEventSink(config, client=client).append((event,))

    rows, destination, job_config = client.load_table_from_json_calls[0]
    assert destination == "supplychain-local.supplychain_raw.canonical_events"
    assert rows[0]["event_id"] == str(event.event_id)
    assert job_config.write_disposition == "WRITE_APPEND"
    assert client.job.result_timeouts == [12.5]
    assert client.insert_rows_json_calls == []
    assert result.rows_submitted == 1
    assert result.job_id == "job-001"


def test_raw_sink_empty_sequence_is_noop() -> None:
    client = FakeBigQueryClient()

    result = BigQueryRawEventSink(
        BigQueryWarehouseConfig(project_id="supplychain-local"),
        client=client,
    ).append(())

    assert result.rows_submitted == 0
    assert result.job_id is None
    assert client.load_table_from_json_calls == []


def test_raw_sink_maps_job_timeout_without_payload_leakage() -> None:
    client = FakeBigQueryClient(job=FakeLoadJob(failure=TimeoutError("payload secret detail")))

    with pytest.raises(WarehouseJobTimeoutError) as exc_info:
        BigQueryRawEventSink(
            BigQueryWarehouseConfig(project_id="supplychain-local"),
            client=client,
        ).append((make_event(),))

    assert "payload" not in str(exc_info.value).lower()
    assert "secret" not in str(exc_info.value).lower()


def test_raw_sink_maps_google_job_failure_without_payload_leakage() -> None:
    client = FakeBigQueryClient(
        job=FakeLoadJob(
            failure=GoogleAPICallError("raw provider payload detail"),  # type: ignore[no-untyped-call]
        )
    )

    with pytest.raises(WarehouseWriteError) as exc_info:
        BigQueryRawEventSink(
            BigQueryWarehouseConfig(project_id="supplychain-local"),
            client=client,
        ).append((make_event(),))

    assert "payload" not in str(exc_info.value).lower()
    assert "provider" not in str(exc_info.value).lower()


def test_bigquery_handler_delegates_one_event_without_ack_or_ledger_behavior() -> None:
    client = FakeBigQueryClient()
    event = make_event()
    handler = BigQueryCanonicalEventHandler(
        BigQueryRawEventSink(
            BigQueryWarehouseConfig(project_id="supplychain-local"),
            client=client,
        )
    )

    handler.handle(event)

    rows, _, _ = client.load_table_from_json_calls[0]
    assert len(rows) == 1
    assert rows[0]["event_id"] == str(event.event_id)


def test_supplier_row_mapping_matches_contract() -> None:
    supplier = make_supplier()

    row_data = supplier_to_core_row(supplier)

    assert row_data == {
        "schema_version": "1.0.0",
        "supplier_id": "SUP-000001",
        "name": "Synthetic Components North",
        "category": "electronic_components",
        "criticality": "HIGH",
        "country_code": "US",
        "region": "WA",
        "city": "Seattle",
        "latitude": 47.6062,
        "longitude": -122.3321,
        "annual_spend_usd": 1_250_000,
        "typical_lead_time_days": 28,
        "dependency_score": 0.74,
        "single_source": True,
    }


def test_supplier_snapshot_loader_uses_write_truncate_load_job() -> None:
    client = FakeBigQueryClient()
    supplier = make_supplier()

    result = BigQuerySupplierSnapshotLoader(
        BigQueryWarehouseConfig(project_id="supplychain-local", job_timeout_seconds=7),
        client=client,
    ).load_snapshot((supplier,))

    rows, destination, job_config = client.load_table_from_json_calls[0]
    assert destination == "supplychain-local.supplychain_core.suppliers"
    assert rows[0]["supplier_id"] == "SUP-000001"
    assert job_config.write_disposition == "WRITE_TRUNCATE"
    assert [field.name for field in job_config.schema] == [
        "schema_version",
        "supplier_id",
        "name",
        "category",
        "criticality",
        "country_code",
        "region",
        "city",
        "latitude",
        "longitude",
        "annual_spend_usd",
        "typical_lead_time_days",
        "dependency_score",
        "single_source",
    ]
    assert client.job.result_timeouts == [7]
    assert result.rows_submitted == 1


def test_warehouse_does_not_close_injected_clients() -> None:
    client = FakeBigQueryClient()
    sink = BigQueryRawEventSink(
        BigQueryWarehouseConfig(project_id="supplychain-local"), client=client
    )
    loader = BigQuerySupplierSnapshotLoader(
        BigQueryWarehouseConfig(project_id="supplychain-local"),
        client=client,
    )

    sink.close()
    loader.close()

    assert client.closed is False


def test_config_requires_explicit_project_and_positive_timeout() -> None:
    with pytest.raises(WarehouseConfigurationError):
        BigQueryWarehouseConfig(project_id=" ")
    with pytest.raises(WarehouseConfigurationError):
        BigQueryWarehouseConfig(project_id="supplychain-local", job_timeout_seconds=0)


def test_core_reference_handles_multiple_keys_independently() -> None:
    first_key = row(event_id="event-1", key="dedup-1")
    second_key_old = row(
        event_id="event-2",
        key="dedup-2",
        revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC),
    )
    second_key_new = row(
        event_id="event-3",
        key="dedup-2",
        fingerprint="sha256:bbb",
        revision=datetime(2026, 8, 28, 12, 0, tzinfo=UTC) + timedelta(minutes=5),
    )

    assert select_authoritative_current([second_key_old, first_key, second_key_new]) == (
        first_key,
        second_key_new,
    )
