from __future__ import annotations

import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any, cast

import pytest
from google.api_core.exceptions import GoogleAPICallError

from supplychain.contracts import CanonicalEvent, EventType
from supplychain.domain import Criticality, Supplier, SupplierCategory, SupplierLocation
from supplychain.risk import SupplierRiskEngine
from supplychain.warehouse import (
    BigQueryRiskAssessmentMartLoader,
    BigQueryRiskInputReader,
    BigQueryWarehouseConfig,
    SupplierRiskBatchService,
    WarehouseJobTimeoutError,
    WarehouseWriteError,
    risk_assessment_to_mart_row,
)

MART_SCHEMA_PATH = (
    Path("infra") / "schemas" / "bigquery" / "mart" / "supplier_risk_assessments.json"
)
BIGQUERY_TF_PATH = Path("infra") / "bigquery.tf"
ASSESSED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


class FakeLoadJob:
    def __init__(self, *, job_id: str = "job-001", failure: Exception | None = None) -> None:
        self.job_id = job_id
        self.failure = failure
        self.result_timeouts: list[float | None] = []

    def result(self, timeout: float | None = None) -> object:
        self.result_timeouts.append(timeout)
        if self.failure is not None:
            raise self.failure
        return object()


class FakeQueryJob:
    def __init__(
        self, rows: Sequence[Mapping[str, Any]], *, failure: Exception | None = None
    ) -> None:
        self.rows = rows
        self.failure = failure
        self.result_timeouts: list[float | None] = []

    def result(self, timeout: float | None = None) -> object:
        self.result_timeouts.append(timeout)
        if self.failure is not None:
            raise self.failure
        return self.rows


class FakeBigQueryClient:
    def __init__(
        self,
        *,
        query_jobs: Sequence[FakeQueryJob] = (),
        load_job: FakeLoadJob | None = None,
    ) -> None:
        self.query_jobs = list(query_jobs)
        self.load_job = FakeLoadJob() if load_job is None else load_job
        self.queries: list[tuple[str, Any]] = []
        self.loads: list[tuple[Sequence[Mapping[str, Any]], str, Any]] = []
        self.insert_rows_json_calls: list[object] = []
        self.closed = False

    def query(self, query: str, *, job_config: object) -> FakeQueryJob:
        self.queries.append((query, job_config))
        return self.query_jobs.pop(0)

    def load_table_from_json(
        self,
        json_rows: Sequence[Mapping[str, Any]],
        destination: str,
        *,
        job_config: object,
    ) -> FakeLoadJob:
        self.loads.append((json_rows, destination, job_config))
        return self.load_job

    def insert_rows_json(self, *args: object, **kwargs: object) -> object:
        self.insert_rows_json_calls.append((args, kwargs))
        raise AssertionError("streaming inserts must not be used")

    def close(self) -> None:
        self.closed = True


@dataclass(frozen=True, slots=True)
class FakeReader:
    suppliers: tuple[Supplier, ...]
    events: tuple[CanonicalEvent, ...]
    calls: list[str]

    def read_suppliers(self) -> tuple[Supplier, ...]:
        self.calls.append("suppliers")
        return self.suppliers

    def read_events(self, assessed_at: datetime) -> tuple[CanonicalEvent, ...]:
        self.calls.append(f"events:{assessed_at.isoformat()}")
        return self.events


class FakeMartLoader:
    def __init__(self, *, fail_history: bool = False) -> None:
        self.fail_history = fail_history
        self.calls: list[tuple[str, tuple[object, ...]]] = []

    def append_history(self, assessments: Sequence[object]) -> object:
        self.calls.append(("history", tuple(assessments)))
        if self.fail_history:
            raise WarehouseWriteError("history failed")
        return object()

    def replace_current(self, assessments: Sequence[object]) -> object:
        self.calls.append(("current", tuple(assessments)))
        return object()


def supplier_row() -> dict[str, object]:
    return {
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


def event_row() -> dict[str, object]:
    return {
        "event_id": "5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10",
        "event_type": "weather.observation.recorded",
        "schema_version": "1.0.0",
        "event_time": ASSESSED_AT,
        "ingested_at": ASSESSED_AT,
        "source_provider": "synthetic-weather",
        "source_endpoint": "synthetic://weather",
        "source_event_id": "weather-001",
        "source_request_id": "request-001",
        "entity_type": "supplier",
        "entity_id": "SUP-000001",
        "location_country_code": "US",
        "location_region": "WA",
        "correlation_id": "corr-001",
        "producer": "risk-test",
        "producer_version": "1.0.0",
        "deduplication_key": "0" * 64,
        "payload": json.dumps(
            {
                "latitude": 47.6062,
                "longitude": -122.3321,
                "temperature_2m_c": 18.4,
                "relative_humidity_2m_pct": 73.0,
                "precipitation_mm": 0.0,
                "rain_mm": 0.0,
                "snowfall_cm": 0.0,
                "weather_code": 3,
                "wind_speed_10m_kmh": 0.0,
                "wind_gusts_10m_kmh": 140.0,
            }
        ),
    }


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


def test_mart_schema_contains_assessment_fields_and_excludes_payload_transport() -> None:
    schema = {field["name"]: field for field in json.loads(MART_SCHEMA_PATH.read_text())}

    assert schema["supplier_id"]["mode"] == "REQUIRED"
    assert schema["assessed_at"]["type"] == "TIMESTAMP"
    assert schema["risk_score"]["type"] == "FLOAT"
    assert schema["risk_level"]["type"] == "STRING"
    assert schema["structural_score"]["type"] == "FLOAT"
    assert schema["evidence_deduplication_keys"]["type"] == "JSON"
    assert "ack_id" not in schema
    assert "delivery_attempt" not in schema
    assert "payload" not in schema
    assert "canonical_event" not in schema


def test_current_and_history_resources_share_schema_with_expected_physical_design() -> None:
    tofu = BIGQUERY_TF_PATH.read_text(encoding="utf-8")

    assert 'resource "google_bigquery_table" "mart_supplier_risk_current"' in tofu
    assert 'resource "google_bigquery_table" "mart_supplier_risk_history"' in tofu
    assert 'table_id            = "supplier_risk_current"' in tofu
    assert 'table_id            = "supplier_risk_history"' in tofu
    assert 'field = "assessed_at"' in tofu
    assert '"risk_level"' in tofu
    assert '"supplier_id"' in tofu
    assert 'data_layer = "mart"' in tofu


def test_risk_assessment_to_mart_row_maps_contract_only() -> None:
    assessment = SupplierRiskEngine().assess(make_supplier(), (), ASSESSED_AT)

    row = risk_assessment_to_mart_row(assessment)

    assert row["model_version"] == "1.0.0"
    assert row["supplier_id"] == "SUP-000001"
    assert row["assessed_at"] == "2026-08-28T12:00:00Z"
    assert row["evidence_deduplication_keys"] == []
    assert "payload" not in row


def test_risk_input_reader_uses_static_bounded_core_queries() -> None:
    client = FakeBigQueryClient(
        query_jobs=(FakeQueryJob([supplier_row()]), FakeQueryJob([event_row()]))
    )
    reader = BigQueryRiskInputReader(
        BigQueryWarehouseConfig(project_id="supplychain-local", job_timeout_seconds=9),
        client=client,
    )

    suppliers = reader.read_suppliers()
    events = reader.read_events(ASSESSED_AT)

    supplier_query, _ = client.queries[0]
    event_query, event_job_config = client.queries[1]
    assert suppliers[0].supplier_id == "SUP-000001"
    assert events[0].event_type is EventType.WEATHER_OBSERVATION_RECORDED
    assert "FROM `supplychain-local.supplychain_core.suppliers`" in supplier_query
    assert "FROM `supplychain-local.supplychain_core.canonical_events`" in event_query
    assert "WHERE event_type IN UNNEST(@event_types)" in event_query
    assert "BETWEEN @earliest_event_time AND @assessed_at" in event_query
    assert len(cast(Any, event_job_config).query_parameters) == 3


def test_risk_input_reader_maps_query_failure_without_payload_leakage() -> None:
    client = FakeBigQueryClient(
        query_jobs=(
            FakeQueryJob(
                [],
                failure=GoogleAPICallError("provider payload detail"),  # type: ignore[no-untyped-call]
            ),
        )
    )
    reader = BigQueryRiskInputReader(BigQueryWarehouseConfig(project_id="local"), client=client)

    with pytest.raises(WarehouseWriteError) as exc_info:
        reader.read_suppliers()

    assert "payload" not in str(exc_info.value)


def test_mart_loader_uses_history_append_and_current_truncate_batch_loads() -> None:
    client = FakeBigQueryClient()
    loader = BigQueryRiskAssessmentMartLoader(
        BigQueryWarehouseConfig(project_id="supplychain-local", job_timeout_seconds=8),
        client=client,
    )
    assessment = SupplierRiskEngine().assess(make_supplier(), (), ASSESSED_AT)

    history = loader.append_history((assessment,))
    current = loader.replace_current((assessment,))

    assert client.loads[0][1] == "supplychain-local.supplychain_mart.supplier_risk_history"
    assert client.loads[0][2].write_disposition == "WRITE_APPEND"
    assert client.loads[1][1] == "supplychain-local.supplychain_mart.supplier_risk_current"
    assert client.loads[1][2].write_disposition == "WRITE_TRUNCATE"
    assert client.insert_rows_json_calls == []
    assert history.rows_submitted == 1
    assert current.rows_submitted == 1


def test_mart_loader_empty_batch_is_noop() -> None:
    client = FakeBigQueryClient()
    loader = BigQueryRiskAssessmentMartLoader(
        BigQueryWarehouseConfig(project_id="supplychain-local"),
        client=client,
    )

    result = loader.append_history(())

    assert result.rows_submitted == 0
    assert client.loads == []


def test_mart_loader_propagates_load_timeout() -> None:
    client = FakeBigQueryClient(load_job=FakeLoadJob(failure=TimeoutError("slow")))
    loader = BigQueryRiskAssessmentMartLoader(
        BigQueryWarehouseConfig(project_id="supplychain-local"),
        client=client,
    )
    assessment = SupplierRiskEngine().assess(make_supplier(), (), ASSESSED_AT)

    with pytest.raises(WarehouseJobTimeoutError):
        loader.append_history((assessment,))


def test_batch_service_reads_once_computes_complete_batch_then_writes_history_current() -> None:
    calls: list[str] = []
    reader = FakeReader(suppliers=(make_supplier(),), events=(), calls=calls)
    loader = FakeMartLoader()
    service = SupplierRiskBatchService(
        reader=cast(Any, reader),
        mart_loader=cast(Any, loader),
    )

    assessments = service.run(ASSESSED_AT)

    assert calls == ["suppliers", "events:2026-08-28T12:00:00+00:00"]
    assert len(assessments) == 1
    assert assessments[0].assessed_at == ASSESSED_AT
    assert [name for name, _ in loader.calls] == ["history", "current"]
    assert loader.calls[0][1] == loader.calls[1][1] == assessments


def test_batch_service_does_not_replace_current_when_history_write_fails() -> None:
    calls: list[str] = []
    reader = FakeReader(suppliers=(make_supplier(),), events=(), calls=calls)
    loader = FakeMartLoader(fail_history=True)
    service = SupplierRiskBatchService(
        reader=cast(Any, reader),
        mart_loader=cast(Any, loader),
    )

    with pytest.raises(WarehouseWriteError):
        service.run(ASSESSED_AT)

    assert [name for name, _ in loader.calls] == ["history"]
