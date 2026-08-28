"""BigQuery load-job warehouse boundary."""

from __future__ import annotations

import math
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from typing import Protocol, cast

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import bigquery

from supplychain.contracts import CanonicalEvent
from supplychain.domain import Supplier
from supplychain.warehouse.errors import (
    WarehouseConfigurationError,
    WarehouseJobTimeoutError,
    WarehouseWriteError,
)
from supplychain.warehouse.rows import (
    BigQueryValue,
    canonical_event_to_raw_row,
    supplier_to_core_row,
)

DEFAULT_BIGQUERY_JOB_TIMEOUT_SECONDS = 60.0
RAW_DATASET_ID = "supplychain_raw"
RAW_CANONICAL_EVENTS_TABLE_ID = "canonical_events"
CORE_DATASET_ID = "supplychain_core"
CORE_CANONICAL_EVENTS_VIEW_ID = "canonical_events"
CORE_SUPPLIERS_TABLE_ID = "suppliers"


class BigQueryLoadJob(Protocol):
    """Subset of a BigQuery load job used by the warehouse boundary."""

    job_id: str

    def result(self, timeout: float | None = None) -> object:
        """Wait for load-job completion."""


class BigQueryClient(Protocol):
    """Subset of the BigQuery client used by Stage 11 load-job writers."""

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


@dataclass(frozen=True, slots=True)
class BigQueryWarehouseConfig:
    """Explicit BigQuery warehouse object configuration."""

    project_id: str
    raw_dataset_id: str = RAW_DATASET_ID
    raw_canonical_events_table_id: str = RAW_CANONICAL_EVENTS_TABLE_ID
    core_dataset_id: str = CORE_DATASET_ID
    core_canonical_events_view_id: str = CORE_CANONICAL_EVENTS_VIEW_ID
    core_suppliers_table_id: str = CORE_SUPPLIERS_TABLE_ID
    job_timeout_seconds: float = DEFAULT_BIGQUERY_JOB_TIMEOUT_SECONDS

    def __post_init__(self) -> None:
        _validate_identifier("project_id", self.project_id)
        _validate_identifier("raw_dataset_id", self.raw_dataset_id)
        _validate_identifier("raw_canonical_events_table_id", self.raw_canonical_events_table_id)
        _validate_identifier("core_dataset_id", self.core_dataset_id)
        _validate_identifier("core_canonical_events_view_id", self.core_canonical_events_view_id)
        _validate_identifier("core_suppliers_table_id", self.core_suppliers_table_id)
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


def _validate_identifier(field_name: str, value: str) -> None:
    if not value.strip():
        raise WarehouseConfigurationError(f"{field_name} must not be blank")
