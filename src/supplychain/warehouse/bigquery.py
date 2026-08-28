"""BigQuery load-job warehouse boundary."""

from __future__ import annotations

import json
import math
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Protocol, cast
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import bigquery
from pydantic import JsonValue

from supplychain.contracts import (
    CanonicalEvent,
    EventType,
)
from supplychain.domain import Criticality, Supplier, SupplierCategory
from supplychain.risk import RiskModelConfig, SupplierRiskAssessment, SupplierRiskEngine
from supplychain.warehouse.errors import (
    WarehouseConfigurationError,
    WarehouseJobTimeoutError,
    WarehouseWriteError,
)
from supplychain.warehouse.rows import (
    BigQueryValue,
    canonical_event_to_raw_row,
    risk_assessment_to_mart_row,
    supplier_to_core_row,
)

DEFAULT_BIGQUERY_JOB_TIMEOUT_SECONDS = 60.0
RAW_DATASET_ID = "supplychain_raw"
RAW_CANONICAL_EVENTS_TABLE_ID = "canonical_events"
CORE_DATASET_ID = "supplychain_core"
CORE_CANONICAL_EVENTS_VIEW_ID = "canonical_events"
CORE_SUPPLIERS_TABLE_ID = "suppliers"
MART_DATASET_ID = "supplychain_mart"
MART_SUPPLIER_RISK_CURRENT_TABLE_ID = "supplier_risk_current"
MART_SUPPLIER_RISK_HISTORY_TABLE_ID = "supplier_risk_history"


class BigQueryLoadJob(Protocol):
    """Subset of a BigQuery load job used by the warehouse boundary."""

    job_id: str

    def result(self, timeout: float | None = None) -> object:
        """Wait for load-job completion."""


class BigQueryQueryJob(Protocol):
    """Subset of a BigQuery query job used by the warehouse boundary."""

    def result(self, timeout: float | None = None) -> object:
        """Wait for query-job completion and return rows."""


class BigQueryClient(Protocol):
    """Subset of the BigQuery client used by load-job writers."""

    def load_table_from_json(
        self,
        json_rows: Sequence[Mapping[str, BigQueryValue]],
        destination: str,
        *,
        job_config: object,
    ) -> BigQueryLoadJob:
        """Submit a JSON load job."""

    def close(self) -> None:
        """Close the client if owned by the caller."""


class BigQueryQueryClient(Protocol):
    """Subset of the BigQuery client used by bounded query readers."""

    def query(self, query: str, *, job_config: object) -> BigQueryQueryJob:
        """Submit a parameterized query job."""

    def close(self) -> None:
        """Close the client if owned by the caller."""


class RiskInputReader(Protocol):
    """Supplier risk batch input boundary."""

    def read_suppliers(self) -> tuple[Supplier, ...]:
        """Read validated Suppliers."""

    def read_events(self, assessed_at: datetime) -> tuple[CanonicalEvent, ...]:
        """Read bounded current Canonical Events."""


class RiskAssessmentMartWriter(Protocol):
    """Supplier risk MART output boundary."""

    def append_history(self, assessments: Sequence[SupplierRiskAssessment]) -> WarehouseLoadResult:
        """Append assessment history."""

    def replace_current(self, assessments: Sequence[SupplierRiskAssessment]) -> WarehouseLoadResult:
        """Replace current assessment snapshot."""


@dataclass(frozen=True, slots=True)
class BigQueryWarehouseConfig:
    """Explicit BigQuery warehouse object configuration."""

    project_id: str
    raw_dataset_id: str = RAW_DATASET_ID
    raw_canonical_events_table_id: str = RAW_CANONICAL_EVENTS_TABLE_ID
    core_dataset_id: str = CORE_DATASET_ID
    core_canonical_events_view_id: str = CORE_CANONICAL_EVENTS_VIEW_ID
    core_suppliers_table_id: str = CORE_SUPPLIERS_TABLE_ID
    mart_dataset_id: str = MART_DATASET_ID
    mart_supplier_risk_current_table_id: str = MART_SUPPLIER_RISK_CURRENT_TABLE_ID
    mart_supplier_risk_history_table_id: str = MART_SUPPLIER_RISK_HISTORY_TABLE_ID
    job_timeout_seconds: float = DEFAULT_BIGQUERY_JOB_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _validate_identifier("project_id", self.project_id)
        _validate_identifier("raw_dataset_id", self.raw_dataset_id)
        _validate_identifier("raw_canonical_events_table_id", self.raw_canonical_events_table_id)
        _validate_identifier("core_dataset_id", self.core_dataset_id)
        _validate_identifier("core_canonical_events_view_id", self.core_canonical_events_view_id)
        _validate_identifier("core_suppliers_table_id", self.core_suppliers_table_id)
        _validate_identifier("mart_dataset_id", self.mart_dataset_id)
        _validate_identifier(
            "mart_supplier_risk_current_table_id",
            self.mart_supplier_risk_current_table_id,
        )
        _validate_identifier(
            "mart_supplier_risk_history_table_id",
            self.mart_supplier_risk_history_table_id,
        )
        if self.job_timeout_seconds <= 0 or not math.isfinite(self.job_timeout_seconds):
            raise WarehouseConfigurationError("BigQuery job timeout must be positive and finite")

    @property
    def raw_canonical_events_table(self) -> str:
        """Return fully qualified RAW canonical_events table ID."""

        return f"{self.project_id}.{self.raw_dataset_id}.{self.raw_canonical_events_table_id}"

    @property
    def core_suppliers_table(self) -> str:
        """Return fully qualified CORE suppliers table ID."""

        return f"{self.project_id}.{self.core_dataset_id}.{self.core_suppliers_table_id}"

    @property
    def core_canonical_events_view(self) -> str:
        """Return fully qualified CORE canonical_events view ID."""

        return f"{self.project_id}.{self.core_dataset_id}.{self.core_canonical_events_view_id}"

    @property
    def mart_supplier_risk_current_table(self) -> str:
        """Return fully qualified MART supplier_risk_current table ID."""

        return (
            f"{self.project_id}.{self.mart_dataset_id}.{self.mart_supplier_risk_current_table_id}"
        )

    @property
    def mart_supplier_risk_history_table(self) -> str:
        """Return fully qualified MART supplier_risk_history table ID."""

        return (
            f"{self.project_id}.{self.mart_dataset_id}.{self.mart_supplier_risk_history_table_id}"
        )


@dataclass(frozen=True, slots=True)
class WarehouseLoadResult:
    """Safe load-job result metadata."""

    table_id: str
    rows_submitted: int
    job_id: str | None


class BigQueryRawEventSink:
    """Append Canonical Events to RAW canonical_events with BigQuery load jobs."""

    def __init__(
        self,
        config: BigQueryWarehouseConfig,
        *,
        client: BigQueryClient | None = None,
    ) -> None:
        self._config = config
        self._client = (
            cast(BigQueryClient, bigquery.Client(project=config.project_id))
            if client is None
            else client
        )
        self._owns_client = client is None

    def append(self, events: Sequence[CanonicalEvent]) -> WarehouseLoadResult:
        """Append validated Canonical Events to RAW or no-op for an empty sequence."""

        rows = tuple(canonical_event_to_raw_row(event) for event in events)
        if not rows:
            return WarehouseLoadResult(
                table_id=self._config.raw_canonical_events_table,
                rows_submitted=0,
                job_id=None,
            )
        job_config = bigquery.LoadJobConfig(
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )
        return _submit_load_job(
            client=self._client,
            rows=rows,
            destination=self._config.raw_canonical_events_table,
            job_config=job_config,
            timeout_seconds=self._config.job_timeout_seconds,
        )

    def close(self) -> None:
        """Close an owned BigQuery client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BigQueryRawEventSink:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class BigQueryCanonicalEventHandler:
    """ProcessingCoordinator handler that appends one event to RAW."""

    def __init__(self, sink: BigQueryRawEventSink) -> None:
        self._sink = sink

    def handle(self, event: CanonicalEvent) -> None:
        """Append one Canonical Event after processing assessment allows handling."""

        self._sink.append((event,))


class BigQuerySupplierSnapshotLoader:
    """Load the authoritative Supplier v1 development snapshot into CORE."""

    def __init__(
        self,
        config: BigQueryWarehouseConfig,
        *,
        client: BigQueryClient | None = None,
    ) -> None:
        self._config = config
        self._client = (
            cast(BigQueryClient, bigquery.Client(project=config.project_id))
            if client is None
            else client
        )
        self._owns_client = client is None

    def load_snapshot(self, suppliers: Sequence[Supplier]) -> WarehouseLoadResult:
        """Replace CORE suppliers with the supplied validated snapshot."""

        rows = tuple(supplier_to_core_row(supplier) for supplier in suppliers)
        if not rows:
            return WarehouseLoadResult(
                table_id=self._config.core_suppliers_table,
                rows_submitted=0,
                job_id=None,
            )
        job_config = bigquery.LoadJobConfig(
            schema=_core_suppliers_schema(),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )
        return _submit_load_job(
            client=self._client,
            rows=rows,
            destination=self._config.core_suppliers_table,
            job_config=job_config,
            timeout_seconds=self._config.job_timeout_seconds,
        )

    def close(self) -> None:
        """Close an owned BigQuery client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BigQuerySupplierSnapshotLoader:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class BigQueryRiskInputReader:
    """Read bounded CORE inputs for deterministic supplier risk batches."""

    def __init__(
        self,
        config: BigQueryWarehouseConfig,
        *,
        client: BigQueryQueryClient | None = None,
        risk_config: RiskModelConfig | None = None,
    ) -> None:
        self._config = config
        self._risk_config = RiskModelConfig() if risk_config is None else risk_config
        self._client = (
            cast(BigQueryQueryClient, bigquery.Client(project=config.project_id))
            if client is None
            else client
        )
        self._owns_client = client is None

    def read_suppliers(self) -> tuple[Supplier, ...]:
        """Read validated Supplier v1 rows from CORE suppliers using a static query."""

        query = f"""
SELECT
  schema_version,
  supplier_id,
  name,
  category,
  criticality,
  country_code,
  region,
  city,
  latitude,
  longitude,
  annual_spend_usd,
  typical_lead_time_days,
  dependency_score,
  single_source
FROM `{self._config.core_suppliers_table}`
ORDER BY supplier_id
""".strip()
        rows = _query_rows(
            client=self._client,
            query=query,
            job_config=bigquery.QueryJobConfig(),
            timeout_seconds=self._config.job_timeout_seconds,
        )
        return tuple(_supplier_from_core_row(row) for row in rows)

    def read_events(self, assessed_at: datetime) -> tuple[CanonicalEvent, ...]:
        """Read bounded current CORE canonical events needed by Risk Model v1."""

        assessment_time = _require_aware_utc(assessed_at)
        earliest = assessment_time - max(
            self._risk_config.weather_lookback,
            self._risk_config.seismic_lookback,
        )
        query = f"""
SELECT
  event_id,
  event_type,
  schema_version,
  event_time,
  ingested_at,
  source_provider,
  source_endpoint,
  source_event_id,
  source_request_id,
  entity_type,
  entity_id,
  location_country_code,
  location_region,
  correlation_id,
  producer,
  producer_version,
  deduplication_key,
  payload
FROM `{self._config.core_canonical_events_view}`
WHERE event_type IN UNNEST(@event_types)
  AND event_time BETWEEN @earliest_event_time AND @assessed_at
ORDER BY event_time ASC, deduplication_key ASC
""".strip()
        job_config = bigquery.QueryJobConfig(
            query_parameters=[
                bigquery.ArrayQueryParameter(
                    "event_types",
                    "STRING",
                    [
                        EventType.WEATHER_OBSERVATION_RECORDED.value,
                        EventType.SEISMIC_EVENT_DETECTED.value,
                    ],
                ),
                bigquery.ScalarQueryParameter("earliest_event_time", "TIMESTAMP", earliest),
                bigquery.ScalarQueryParameter("assessed_at", "TIMESTAMP", assessment_time),
            ]
        )
        rows = _query_rows(
            client=self._client,
            query=query,
            job_config=job_config,
            timeout_seconds=self._config.job_timeout_seconds,
        )
        return tuple(_canonical_event_from_core_row(row) for row in rows)

    def close(self) -> None:
        """Close an owned BigQuery client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BigQueryRiskInputReader:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class BigQueryRiskAssessmentMartLoader:
    """Write SupplierRiskAssessment batches to MART through BigQuery load jobs."""

    def __init__(
        self,
        config: BigQueryWarehouseConfig,
        *,
        client: BigQueryClient | None = None,
    ) -> None:
        self._config = config
        self._client = (
            cast(BigQueryClient, bigquery.Client(project=config.project_id))
            if client is None
            else client
        )
        self._owns_client = client is None

    def append_history(self, assessments: Sequence[SupplierRiskAssessment]) -> WarehouseLoadResult:
        """Append one complete assessment batch to MART supplier_risk_history."""

        return self._load_assessments(
            assessments,
            destination=self._config.mart_supplier_risk_history_table,
            write_disposition=bigquery.WriteDisposition.WRITE_APPEND,
        )

    def replace_current(self, assessments: Sequence[SupplierRiskAssessment]) -> WarehouseLoadResult:
        """Replace the MART supplier_risk_current snapshot with one complete batch."""

        return self._load_assessments(
            assessments,
            destination=self._config.mart_supplier_risk_current_table,
            write_disposition=bigquery.WriteDisposition.WRITE_TRUNCATE,
        )

    def _load_assessments(
        self,
        assessments: Sequence[SupplierRiskAssessment],
        *,
        destination: str,
        write_disposition: str,
    ) -> WarehouseLoadResult:
        rows = tuple(risk_assessment_to_mart_row(assessment) for assessment in assessments)
        if not rows:
            return WarehouseLoadResult(table_id=destination, rows_submitted=0, job_id=None)
        job_config = bigquery.LoadJobConfig(
            schema=_supplier_risk_schema(),
            source_format=bigquery.SourceFormat.NEWLINE_DELIMITED_JSON,
            write_disposition=write_disposition,
        )
        return _submit_load_job(
            client=self._client,
            rows=rows,
            destination=destination,
            job_config=job_config,
            timeout_seconds=self._config.job_timeout_seconds,
        )

    def close(self) -> None:
        """Close an owned BigQuery client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> BigQueryRiskAssessmentMartLoader:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class SupplierRiskBatchService:
    """Compute a complete supplier risk batch before writing MART outputs."""

    def __init__(
        self,
        *,
        reader: RiskInputReader,
        mart_loader: RiskAssessmentMartWriter,
        engine: SupplierRiskEngine | None = None,
    ) -> None:
        self._reader = reader
        self._mart_loader = mart_loader
        self._engine = SupplierRiskEngine() if engine is None else engine

    def run(self, assessed_at: datetime) -> tuple[SupplierRiskAssessment, ...]:
        """Compute all assessments, append history, then replace current snapshot."""

        assessment_time = _require_aware_utc(assessed_at)
        suppliers = self._reader.read_suppliers()
        events = self._reader.read_events(assessment_time)
        assessments = tuple(
            self._engine.assess(supplier, events, assessment_time) for supplier in suppliers
        )
        self._mart_loader.append_history(assessments)
        self._mart_loader.replace_current(assessments)
        return assessments


def _submit_load_job(
    *,
    client: BigQueryClient,
    rows: Sequence[Mapping[str, BigQueryValue]],
    destination: str,
    job_config: object,
    timeout_seconds: float,
) -> WarehouseLoadResult:
    try:
        job = client.load_table_from_json(rows, destination, job_config=job_config)
        job.result(timeout=timeout_seconds)
    except TimeoutError as exc:
        raise WarehouseJobTimeoutError("BigQuery load job timed out") from exc
    except (GoogleAPICallError, RetryError) as exc:
        raise WarehouseWriteError("BigQuery load job failed") from exc
    return WarehouseLoadResult(
        table_id=destination,
        rows_submitted=len(rows),
        job_id=job.job_id,
    )


def _query_rows(
    *,
    client: BigQueryQueryClient,
    query: str,
    job_config: object,
    timeout_seconds: float,
) -> tuple[object, ...]:
    try:
        job = client.query(query, job_config=job_config)
        rows = job.result(timeout=timeout_seconds)
    except TimeoutError as exc:
        raise WarehouseJobTimeoutError("BigQuery query job timed out") from exc
    except (GoogleAPICallError, RetryError) as exc:
        raise WarehouseWriteError("BigQuery query job failed") from exc
    return tuple(cast(Iterable[object], rows))


def _core_suppliers_schema() -> tuple[bigquery.SchemaField, ...]:
    return (
        bigquery.SchemaField(
            "schema_version",
            "STRING",
            mode="REQUIRED",
            description="Supplier contract schema version.",
        ),
        bigquery.SchemaField(
            "supplier_id",
            "STRING",
            mode="REQUIRED",
            description="Supplier v1 logical master-data key.",
        ),
        bigquery.SchemaField(
            "name", "STRING", mode="REQUIRED", description="Supplier display name."
        ),
        bigquery.SchemaField(
            "category",
            "STRING",
            mode="REQUIRED",
            description="Supplier category taxonomy value.",
        ),
        bigquery.SchemaField(
            "criticality",
            "STRING",
            mode="REQUIRED",
            description="Operational criticality taxonomy value.",
        ),
        bigquery.SchemaField(
            "country_code",
            "STRING",
            mode="REQUIRED",
            description="Supplier location country code.",
        ),
        bigquery.SchemaField(
            "region",
            "STRING",
            mode="REQUIRED",
            description="Supplier location region.",
        ),
        bigquery.SchemaField(
            "city", "STRING", mode="REQUIRED", description="Supplier location city."
        ),
        bigquery.SchemaField(
            "latitude",
            "FLOAT",
            mode="REQUIRED",
            description="Supplier location latitude.",
        ),
        bigquery.SchemaField(
            "longitude",
            "FLOAT",
            mode="REQUIRED",
            description="Supplier location longitude.",
        ),
        bigquery.SchemaField(
            "annual_spend_usd",
            "INTEGER",
            mode="REQUIRED",
            description="Annual spend in whole US dollars.",
        ),
        bigquery.SchemaField(
            "typical_lead_time_days",
            "INTEGER",
            mode="REQUIRED",
            description="Typical lead time in whole days.",
        ),
        bigquery.SchemaField(
            "dependency_score",
            "FLOAT",
            mode="REQUIRED",
            description="Supplier dependency score from 0.0 through 1.0.",
        ),
        bigquery.SchemaField(
            "single_source",
            "BOOLEAN",
            mode="REQUIRED",
            description="Whether this supplier is currently single-sourced.",
        ),
    )


def _supplier_risk_schema() -> tuple[bigquery.SchemaField, ...]:
    return (
        bigquery.SchemaField(
            "model_version",
            "STRING",
            mode="REQUIRED",
            description="Deterministic Supplier Risk Model version.",
        ),
        bigquery.SchemaField(
            "supplier_id",
            "STRING",
            mode="REQUIRED",
            description="Supplier v1 logical master-data key.",
        ),
        bigquery.SchemaField(
            "assessed_at",
            "TIMESTAMP",
            mode="REQUIRED",
            description="Explicit UTC assessment timestamp.",
        ),
        bigquery.SchemaField(
            "risk_score",
            "FLOAT",
            mode="REQUIRED",
            description="Overall deterministic 0..100 risk score.",
        ),
        bigquery.SchemaField(
            "risk_level",
            "STRING",
            mode="REQUIRED",
            description="Risk level derived from the overall risk score.",
        ),
        bigquery.SchemaField(
            "structural_score",
            "FLOAT",
            mode="REQUIRED",
            description="Structural supplier risk score from 0 through 100.",
        ),
        bigquery.SchemaField(
            "weather_score",
            "FLOAT",
            mode="REQUIRED",
            description="Weather risk score from 0 through 100.",
        ),
        bigquery.SchemaField(
            "seismic_score",
            "FLOAT",
            mode="REQUIRED",
            description="Seismic risk score from 0 through 100.",
        ),
        bigquery.SchemaField(
            "criticality_component",
            "FLOAT",
            mode="REQUIRED",
            description="Normalized structural criticality component from 0 through 1.",
        ),
        bigquery.SchemaField(
            "dependency_component",
            "FLOAT",
            mode="REQUIRED",
            description="Normalized structural dependency component from 0 through 1.",
        ),
        bigquery.SchemaField(
            "single_source_component",
            "FLOAT",
            mode="REQUIRED",
            description="Normalized single-source component from 0 through 1.",
        ),
        bigquery.SchemaField(
            "lead_time_component",
            "FLOAT",
            mode="REQUIRED",
            description="Normalized lead-time component from 0 through 1.",
        ),
        bigquery.SchemaField(
            "relevant_weather_event_count",
            "INTEGER",
            mode="REQUIRED",
            description="Count of relevant weather observations used as evidence.",
        ),
        bigquery.SchemaField(
            "relevant_seismic_event_count",
            "INTEGER",
            mode="REQUIRED",
            description="Count of relevant seismic events used as evidence.",
        ),
        bigquery.SchemaField(
            "evidence_deduplication_keys",
            "JSON",
            mode="REQUIRED",
            description=(
                "Deterministically ordered canonical event deduplication keys used as evidence."
            ),
        ),
        bigquery.SchemaField(
            "dominant_factor",
            "STRING",
            mode="REQUIRED",
            description="Risk family with the largest weighted contribution.",
        ),
    )


def _supplier_from_core_row(row: object) -> Supplier:
    return Supplier.model_validate(
        {
            "schema_version": _row_value(row, "schema_version"),
            "supplier_id": _row_value(row, "supplier_id"),
            "name": _row_value(row, "name"),
            "category": SupplierCategory(str(_row_value(row, "category"))),
            "criticality": Criticality(str(_row_value(row, "criticality"))),
            "location": {
                "country_code": _row_value(row, "country_code"),
                "region": _row_value(row, "region"),
                "city": _row_value(row, "city"),
                "latitude": _row_value(row, "latitude"),
                "longitude": _row_value(row, "longitude"),
            },
            "annual_spend_usd": _row_value(row, "annual_spend_usd"),
            "typical_lead_time_days": _row_value(row, "typical_lead_time_days"),
            "dependency_score": _row_value(row, "dependency_score"),
            "single_source": _row_value(row, "single_source"),
        }
    )


def _canonical_event_from_core_row(row: object) -> CanonicalEvent:
    entity_type = _row_value(row, "entity_type")
    entity_id = _row_value(row, "entity_id")
    country_code = _row_value(row, "location_country_code")
    region = _row_value(row, "location_region")
    return CanonicalEvent.model_validate(
        {
            "event_id": UUID(str(_row_value(row, "event_id"))),
            "event_type": EventType(str(_row_value(row, "event_type"))),
            "schema_version": _row_value(row, "schema_version"),
            "event_time": _row_value(row, "event_time"),
            "ingested_at": _row_value(row, "ingested_at"),
            "source": {
                "provider": _row_value(row, "source_provider"),
                "endpoint": _row_value(row, "source_endpoint"),
                "source_event_id": _row_value(row, "source_event_id"),
                "request_id": _row_value(row, "source_request_id"),
            },
            "entity": (
                None
                if entity_type is None or entity_id is None
                else {"type": entity_type, "id": entity_id}
            ),
            "location": (
                None
                if country_code is None and region is None
                else {"country_code": country_code, "region": region}
            ),
            "payload": _row_payload(row),
            "metadata": {
                "correlation_id": _row_value(row, "correlation_id"),
                "producer": _row_value(row, "producer"),
                "producer_version": _row_value(row, "producer_version"),
                "deduplication_key": _row_value(row, "deduplication_key"),
            },
        }
    )


def _row_payload(row: object) -> dict[str, JsonValue]:
    payload = _row_value(row, "payload")
    if isinstance(payload, str):
        decoded = json.loads(payload)
        if isinstance(decoded, dict):
            return cast(dict[str, JsonValue], dict(decoded))
    if isinstance(payload, dict):
        return cast(dict[str, JsonValue], payload)
    raise WarehouseWriteError("CORE canonical event payload is not a JSON object")


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return row[name]
    return getattr(row, name)


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise WarehouseConfigurationError("assessment timestamp must be timezone-aware")
    return value.astimezone(UTC)


def _validate_identifier(field_name: str, value: str) -> None:
    if not value.strip():
        raise WarehouseConfigurationError(f"{field_name} must not be blank")
