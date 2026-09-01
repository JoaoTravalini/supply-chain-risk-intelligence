"""Guarded BigQuery data access for agent investigations."""

from __future__ import annotations

import json
import math
import os
import time
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime
from importlib.resources import files
from typing import Annotated, Protocol, cast
from uuid import UUID

from google.api_core.exceptions import GoogleAPICallError, RetryError
from google.cloud import bigquery
from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

from supplychain.contracts import CanonicalEvent, EventType
from supplychain.domain import Criticality, Supplier, SupplierCategory
from supplychain.observability import ObservabilityRuntime
from supplychain.observability.runtime import TelemetryOutcome, elapsed_ms
from supplychain.risk import RiskFactorFamily, RiskLevel, SupplierRiskAssessment
from supplychain.risk.models import EvidenceKey, SupplierId
from supplychain.warehouse import (
    CORE_CANONICAL_EVENTS_VIEW_ID,
    CORE_DATASET_ID,
    CORE_SUPPLIERS_TABLE_ID,
    DEFAULT_BIGQUERY_JOB_TIMEOUT_SECONDS,
    MART_DATASET_ID,
    MART_SUPPLIER_RISK_CURRENT_TABLE_ID,
    MART_SUPPLIER_RISK_HISTORY_TABLE_ID,
)

SUPPLYCHAIN_GCP_PROJECT_ID_ENV = "SUPPLYCHAIN_GCP_PROJECT_ID"
AGENT_BIGQUERY_MAX_BYTES_BILLED_ENV = "SUPPLYCHAIN_AGENT_BIGQUERY_MAX_BYTES_BILLED"
DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED = 100 * 1024 * 1024
DEFAULT_RISK_HISTORY_LIMIT = 20
MAX_RISK_HISTORY_LIMIT = 100
MAX_EVIDENCE_KEYS = 50

APPLICATION_LABEL = "supplychain-sentinel"
COMPONENT_LABEL = "agent-data-access"
ENVIRONMENT_LABEL = "development"

NonEmptyString = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True, strict=True)]


class AgentDataError(Exception):
    """Base class for agent data-access failures."""


class AgentDataConfigurationError(AgentDataError):
    """Raised when agent data-access configuration is invalid."""


class AgentDataNotFoundError(AgentDataError):
    """Raised when an approved lookup finds no matching data."""


class AgentDataIntegrityError(AgentDataError):
    """Raised when warehouse data violates expected cardinality or shape."""


class QueryBudgetExceededError(AgentDataError):
    """Raised when dry-run estimated bytes exceed the configured budget."""


class AgentDataQueryError(AgentDataError):
    """Raised when BigQuery read execution fails."""


class BigQueryReadJob(Protocol):
    """Subset of BigQuery query job behavior used by the guarded reader."""

    total_bytes_processed: int

    def result(self, timeout: float | None = None) -> object:
        """Return query rows."""


class BigQueryReadClient(Protocol):
    """Subset of BigQuery client behavior used by the guarded reader."""

    def query(self, query: str, *, job_config: object) -> BigQueryReadJob:
        """Submit a BigQuery query job."""

    def close(self) -> None:
        """Close the client if owned by the service."""


class StrictAgentDataModel(BaseModel):
    """Base for immutable strict agent data tool models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SupplierLookupInput(StrictAgentDataModel):
    """Input for supplier-scoped lookups."""

    supplier_id: SupplierId


class RiskHistoryInput(SupplierLookupInput):
    """Input for bounded supplier risk history lookup."""

    limit: int = Field(default=DEFAULT_RISK_HISTORY_LIMIT, ge=1, le=MAX_RISK_HISTORY_LIMIT)


class RiskEvidenceInput(StrictAgentDataModel):
    """Input for canonical risk-evidence lookup."""

    evidence_deduplication_keys: tuple[EvidenceKey, ...] = Field(max_length=MAX_EVIDENCE_KEYS)

    @field_validator("evidence_deduplication_keys")
    @classmethod
    def reject_too_many_distinct_keys(cls, value: tuple[str, ...]) -> tuple[str, ...]:
        if len(set(value)) > MAX_EVIDENCE_KEYS:
            raise ValueError("too many evidence deduplication keys")
        return value


@dataclass(frozen=True, slots=True)
class AgentBigQueryConfig:
    """Configuration for guarded agent BigQuery reads."""

    project_id: str
    max_bytes_billed: int = DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED
    query_timeout_seconds: float = DEFAULT_BIGQUERY_JOB_TIMEOUT_SECONDS
    default_history_limit: int = DEFAULT_RISK_HISTORY_LIMIT
    max_history_limit: int = MAX_RISK_HISTORY_LIMIT
    max_evidence_keys: int = MAX_EVIDENCE_KEYS
    core_dataset_id: str = CORE_DATASET_ID
    core_suppliers_table_id: str = CORE_SUPPLIERS_TABLE_ID
    core_canonical_events_view_id: str = CORE_CANONICAL_EVENTS_VIEW_ID
    mart_dataset_id: str = MART_DATASET_ID
    mart_supplier_risk_current_table_id: str = MART_SUPPLIER_RISK_CURRENT_TABLE_ID
    mart_supplier_risk_history_table_id: str = MART_SUPPLIER_RISK_HISTORY_TABLE_ID

    def __post_init__(self) -> None:
        _validate_identifier("project_id", self.project_id)
        _validate_positive_int("max_bytes_billed", self.max_bytes_billed)
        _validate_positive_finite("query_timeout_seconds", self.query_timeout_seconds)
        _validate_limit("default_history_limit", self.default_history_limit, self.max_history_limit)
        _validate_limit("max_history_limit", self.max_history_limit, MAX_RISK_HISTORY_LIMIT)
        _validate_limit("max_evidence_keys", self.max_evidence_keys, MAX_EVIDENCE_KEYS)
        for name in (
            "core_dataset_id",
            "core_suppliers_table_id",
            "core_canonical_events_view_id",
            "mart_dataset_id",
            "mart_supplier_risk_current_table_id",
            "mart_supplier_risk_history_table_id",
        ):
            _validate_identifier(name, str(getattr(self, name)))

    @property
    def core_suppliers_table(self) -> str:
        """Return the approved CORE suppliers table."""

        return f"{self.project_id}.{self.core_dataset_id}.{self.core_suppliers_table_id}"

    @property
    def core_canonical_events_view(self) -> str:
        """Return the approved CORE canonical event view."""

        return f"{self.project_id}.{self.core_dataset_id}.{self.core_canonical_events_view_id}"

    @property
    def mart_supplier_risk_current_table(self) -> str:
        """Return the approved MART current-risk table."""

        return (
            f"{self.project_id}.{self.mart_dataset_id}.{self.mart_supplier_risk_current_table_id}"
        )

    @property
    def mart_supplier_risk_history_table(self) -> str:
        """Return the approved MART risk-history table."""

        return (
            f"{self.project_id}.{self.mart_dataset_id}.{self.mart_supplier_risk_history_table_id}"
        )


@dataclass(frozen=True, slots=True)
class QueryExecutionSummary:
    """Safe query execution metadata for smoke validation and observability."""

    operation_name: str
    estimated_bytes_processed: int
    maximum_bytes_billed: int
    row_count: int


@dataclass(frozen=True, slots=True)
class _QuerySpec:
    name: str
    sql: str
    parameters: tuple[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter, ...]
    max_result_rows: int


class GuardedBigQueryReader:
    """Execute only project-owned SELECT query specifications with cost guards."""

    def __init__(
        self,
        config: AgentBigQueryConfig,
        *,
        client: BigQueryReadClient | None = None,
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._config = config
        self._client = (
            cast(BigQueryReadClient, bigquery.Client(project=config.project_id))
            if client is None
            else client
        )
        self._owns_client = client is None
        self._executions: list[QueryExecutionSummary] = []
        self._observability = observability or ObservabilityRuntime.disabled()

    @property
    def executions(self) -> tuple[QueryExecutionSummary, ...]:
        """Return safe execution summaries for completed queries."""

        return tuple(self._executions)

    def read(self, spec: _QuerySpec) -> tuple[object, ...]:
        """Run dry-run budget validation before executing an allowlisted query."""

        started_at = time.perf_counter()
        estimated_bytes: int | None = None
        row_count: int | None = None
        with self._observability.span(
            "supplychain.bigquery.read",
            attributes={
                "component": "bigquery",
                "operation": spec.name,
            },
        ) as span:
            try:
                estimated_bytes = self._dry_run(spec)
                if span is not None:
                    span.set_attribute("estimated_bytes", estimated_bytes)
                    span.set_attribute("maximum_bytes_billed", self._config.max_bytes_billed)
                if estimated_bytes > self._config.max_bytes_billed:
                    self._observability.record_bigquery_read(
                        operation=spec.name,
                        outcome=TelemetryOutcome.BUDGET_REJECTED,
                        estimated_bytes=estimated_bytes,
                        maximum_bytes_billed=self._config.max_bytes_billed,
                        row_count=None,
                        duration_ms=elapsed_ms(started_at),
                        error_category="budget",
                    )
                    self._observability.set_span_status(span, TelemetryOutcome.BUDGET_REJECTED)
                    raise QueryBudgetExceededError(
                        "BigQuery query estimate exceeds budget: "
                        f"estimated_bytes={estimated_bytes} "
                        f"allowed_bytes={self._config.max_bytes_billed}"
                    )
                rows = self._execute(spec)
                row_count = len(rows)
                if row_count > spec.max_result_rows:
                    raise AgentDataIntegrityError("BigQuery query returned too many rows")
                self._executions.append(
                    QueryExecutionSummary(
                        operation_name=spec.name,
                        estimated_bytes_processed=estimated_bytes,
                        maximum_bytes_billed=self._config.max_bytes_billed,
                        row_count=row_count,
                    )
                )
                if span is not None:
                    span.set_attribute("row_count", row_count)
                self._observability.record_bigquery_read(
                    operation=spec.name,
                    outcome=TelemetryOutcome.SUCCESS,
                    estimated_bytes=estimated_bytes,
                    maximum_bytes_billed=self._config.max_bytes_billed,
                    row_count=row_count,
                    duration_ms=elapsed_ms(started_at),
                )
                self._observability.set_span_status(span, TelemetryOutcome.SUCCESS)
                return rows
            except QueryBudgetExceededError:
                raise
            except Exception:
                self._observability.record_bigquery_read(
                    operation=spec.name,
                    outcome=TelemetryOutcome.FAILURE,
                    estimated_bytes=estimated_bytes,
                    maximum_bytes_billed=self._config.max_bytes_billed,
                    row_count=row_count,
                    duration_ms=elapsed_ms(started_at),
                    error_category="query",
                )
                self._observability.set_span_status(span, TelemetryOutcome.FAILURE)
                raise

    def _dry_run(self, spec: _QuerySpec) -> int:
        job_config = _query_job_config(
            parameters=spec.parameters,
            max_bytes_billed=self._config.max_bytes_billed,
            dry_run=True,
            use_query_cache=False,
        )
        try:
            job = self._client.query(spec.sql, job_config=job_config)
        except (GoogleAPICallError, RetryError, Exception) as exc:
            raise AgentDataQueryError("BigQuery dry run failed") from exc
        return int(getattr(job, "total_bytes_processed", 0))

    def _execute(self, spec: _QuerySpec) -> tuple[object, ...]:
        job_config = _query_job_config(
            parameters=spec.parameters,
            max_bytes_billed=self._config.max_bytes_billed,
            dry_run=False,
            use_query_cache=None,
        )
        try:
            job = self._client.query(spec.sql, job_config=job_config)
            rows = job.result(timeout=self._config.query_timeout_seconds)
        except TimeoutError as exc:
            raise AgentDataQueryError("BigQuery query timed out") from exc
        except (GoogleAPICallError, RetryError, Exception) as exc:
            raise AgentDataQueryError("BigQuery query failed") from exc
        return tuple(cast(Iterable[object], rows))

    def close(self) -> None:
        """Close an owned BigQuery client; injected clients remain caller-owned."""

        if self._owns_client:
            self._client.close()

    def __enter__(self) -> GuardedBigQueryReader:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()


class AgentDataService:
    """Typed read-only data service for future agent tools."""

    def __init__(self, config: AgentBigQueryConfig, *, reader: GuardedBigQueryReader) -> None:
        self._config = config
        self._reader = reader

    @property
    def executions(self) -> tuple[QueryExecutionSummary, ...]:
        """Return safe BigQuery execution summaries."""

        return self._reader.executions

    def get_supplier_profile(self, request: SupplierLookupInput) -> Supplier:
        """Return one validated Supplier profile from CORE."""

        rows = self._reader.read(_supplier_profile_spec(self._config, request.supplier_id))
        if not rows:
            raise AgentDataNotFoundError("Supplier profile was not found")
        if len(rows) > 1:
            raise AgentDataIntegrityError("Supplier profile lookup returned duplicate rows")
        return _supplier_from_row(rows[0])

    def get_current_supplier_risk(self, request: SupplierLookupInput) -> SupplierRiskAssessment:
        """Return the authoritative current Supplier risk assessment from MART."""

        rows = self._reader.read(_current_risk_spec(self._config, request.supplier_id))
        if not rows:
            raise AgentDataNotFoundError("Current supplier risk was not found")
        if len(rows) > 1:
            raise AgentDataIntegrityError("Current supplier risk lookup returned duplicate rows")
        return _risk_assessment_from_row(rows[0])

    def get_supplier_risk_history(
        self,
        request: RiskHistoryInput,
    ) -> tuple[SupplierRiskAssessment, ...]:
        """Return bounded Supplier risk history ordered newest first."""

        rows = self._reader.read(
            _risk_history_spec(self._config, request.supplier_id, request.limit)
        )
        if len(rows) > request.limit:
            raise AgentDataIntegrityError("Supplier risk history exceeded requested limit")
        return tuple(_risk_assessment_from_row(row) for row in rows)

    def get_risk_evidence(self, request: RiskEvidenceInput) -> tuple[CanonicalEvent, ...]:
        """Return Canonical Events by stable risk evidence deduplication keys."""

        keys = tuple(sorted(set(request.evidence_deduplication_keys)))
        if not keys:
            return ()
        if len(keys) > self._config.max_evidence_keys:
            raise AgentDataConfigurationError("Too many evidence keys requested")
        rows = self._reader.read(_risk_evidence_spec(self._config, keys))
        if len(rows) > len(keys):
            raise AgentDataIntegrityError("Risk evidence lookup returned duplicate rows")
        return tuple(_canonical_event_from_row(row) for row in rows)


def agent_data_service_from_env() -> AgentDataService:
    """Create an AgentDataService from safe environment configuration."""

    config = agent_bigquery_config_from_env()
    return AgentDataService(config, reader=GuardedBigQueryReader(config))


def agent_bigquery_config_from_env() -> AgentBigQueryConfig:
    """Read agent BigQuery configuration from environment variables."""

    project_id = os.environ.get(SUPPLYCHAIN_GCP_PROJECT_ID_ENV)
    if project_id is None or not project_id.strip():
        raise AgentDataConfigurationError(f"{SUPPLYCHAIN_GCP_PROJECT_ID_ENV} must be set")
    max_bytes_value = os.environ.get(AGENT_BIGQUERY_MAX_BYTES_BILLED_ENV)
    max_bytes = (
        DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED
        if max_bytes_value is None or not max_bytes_value.strip()
        else _parse_positive_int(AGENT_BIGQUERY_MAX_BYTES_BILLED_ENV, max_bytes_value)
    )
    return AgentBigQueryConfig(project_id=project_id, max_bytes_billed=max_bytes)


def approved_agent_data_tools(service: AgentDataService) -> Mapping[str, object]:
    """Return the framework-neutral allowlist of approved data operations."""

    return {
        "get_supplier_profile": service.get_supplier_profile,
        "get_current_supplier_risk": service.get_current_supplier_risk,
        "get_supplier_risk_history": service.get_supplier_risk_history,
        "get_risk_evidence": service.get_risk_evidence,
    }


def _query_job_config(
    *,
    parameters: Sequence[bigquery.ScalarQueryParameter | bigquery.ArrayQueryParameter],
    max_bytes_billed: int,
    dry_run: bool,
    use_query_cache: bool | None,
) -> bigquery.QueryJobConfig:
    kwargs: dict[str, object] = {
        "query_parameters": list(parameters),
        "maximum_bytes_billed": max_bytes_billed,
        "use_legacy_sql": False,
        "dry_run": dry_run,
        "labels": {
            "application": APPLICATION_LABEL,
            "component": COMPONENT_LABEL,
            "environment": ENVIRONMENT_LABEL,
        },
    }
    if use_query_cache is not None:
        kwargs["use_query_cache"] = use_query_cache
    return bigquery.QueryJobConfig(**kwargs)


def _supplier_profile_spec(config: AgentBigQueryConfig, supplier_id: str) -> _QuerySpec:
    return _QuerySpec(
        name="get_supplier_profile",
        sql=_sql("supplier_profile").format(core_suppliers_table=config.core_suppliers_table),
        parameters=(bigquery.ScalarQueryParameter("supplier_id", "STRING", supplier_id),),
        max_result_rows=1,
    )


def _current_risk_spec(config: AgentBigQueryConfig, supplier_id: str) -> _QuerySpec:
    return _QuerySpec(
        name="get_current_supplier_risk",
        sql=_sql("current_supplier_risk").format(
            mart_supplier_risk_current_table=config.mart_supplier_risk_current_table
        ),
        parameters=(bigquery.ScalarQueryParameter("supplier_id", "STRING", supplier_id),),
        max_result_rows=1,
    )


def _risk_history_spec(config: AgentBigQueryConfig, supplier_id: str, limit: int) -> _QuerySpec:
    return _QuerySpec(
        name="get_supplier_risk_history",
        sql=_sql("supplier_risk_history").format(
            mart_supplier_risk_history_table=config.mart_supplier_risk_history_table
        ),
        parameters=(
            bigquery.ScalarQueryParameter("supplier_id", "STRING", supplier_id),
            bigquery.ScalarQueryParameter("limit", "INT64", limit),
        ),
        max_result_rows=limit,
    )


def _risk_evidence_spec(config: AgentBigQueryConfig, keys: tuple[str, ...]) -> _QuerySpec:
    return _QuerySpec(
        name="get_risk_evidence",
        sql=_sql("risk_evidence").format(
            core_canonical_events_view=config.core_canonical_events_view
        ),
        parameters=(
            bigquery.ArrayQueryParameter("evidence_deduplication_keys", "STRING", list(keys)),
        ),
        max_result_rows=len(keys),
    )


def _sql(name: str) -> str:
    return (files("supplychain.agent.sql") / f"{name}.sql").read_text(encoding="utf-8").strip()


def _supplier_from_row(row: object) -> Supplier:
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


def _risk_assessment_from_row(row: object) -> SupplierRiskAssessment:
    return SupplierRiskAssessment.model_validate(
        {
            "model_version": _row_value(row, "model_version"),
            "supplier_id": _row_value(row, "supplier_id"),
            "assessed_at": _require_aware_utc(_row_value(row, "assessed_at")),
            "risk_score": _row_value(row, "risk_score"),
            "risk_level": RiskLevel(str(_row_value(row, "risk_level"))),
            "structural_score": _row_value(row, "structural_score"),
            "weather_score": _row_value(row, "weather_score"),
            "seismic_score": _row_value(row, "seismic_score"),
            "structural": {
                "criticality_component": _row_value(row, "criticality_component"),
                "dependency_component": _row_value(row, "dependency_component"),
                "single_source_component": _row_value(row, "single_source_component"),
                "lead_time_component": _row_value(row, "lead_time_component"),
            },
            "relevant_weather_event_count": _row_value(row, "relevant_weather_event_count"),
            "relevant_seismic_event_count": _row_value(row, "relevant_seismic_event_count"),
            "evidence_deduplication_keys": _json_array(row, "evidence_deduplication_keys"),
            "dominant_factor": RiskFactorFamily(str(_row_value(row, "dominant_factor"))),
        }
    )


def _canonical_event_from_row(row: object) -> CanonicalEvent:
    entity_type = _row_value(row, "entity_type")
    entity_id = _row_value(row, "entity_id")
    country_code = _row_value(row, "location_country_code")
    region = _row_value(row, "location_region")
    return CanonicalEvent.model_validate(
        {
            "event_id": UUID(str(_row_value(row, "event_id"))),
            "event_type": EventType(str(_row_value(row, "event_type"))),
            "schema_version": _row_value(row, "schema_version"),
            "event_time": _require_aware_utc(_row_value(row, "event_time")),
            "ingested_at": _require_aware_utc(_row_value(row, "ingested_at")),
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
            "payload": _payload(row),
            "metadata": {
                "correlation_id": _row_value(row, "correlation_id"),
                "producer": _row_value(row, "producer"),
                "producer_version": _row_value(row, "producer_version"),
                "deduplication_key": _row_value(row, "deduplication_key"),
            },
        }
    )


def _json_array(row: object, name: str) -> tuple[str, ...]:
    value = _row_value(row, name)
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise AgentDataIntegrityError("JSON field is malformed") from exc
    if not isinstance(decoded, list):
        raise AgentDataIntegrityError("JSON field is not an array")
    return tuple(str(item) for item in decoded)


def _payload(row: object) -> dict[str, JsonValue]:
    value = _row_value(row, "payload")
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise AgentDataIntegrityError("Canonical event payload is malformed") from exc
    if not isinstance(decoded, dict):
        raise AgentDataIntegrityError("Canonical event payload is not a JSON object")
    return cast(dict[str, JsonValue], dict(decoded))


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return row[name]
    return getattr(row, name)


def _require_aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AgentDataIntegrityError("timestamp field is not a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise AgentDataIntegrityError("timestamp field is not timezone-aware")
    return value.astimezone(UTC)


def _validate_identifier(field_name: str, value: str) -> None:
    if not value.strip():
        raise AgentDataConfigurationError(f"{field_name} must not be blank")


def _validate_positive_int(field_name: str, value: int) -> None:
    if value <= 0:
        raise AgentDataConfigurationError(f"{field_name} must be positive")


def _validate_positive_finite(field_name: str, value: float) -> None:
    if value <= 0 or not math.isfinite(value):
        raise AgentDataConfigurationError(f"{field_name} must be positive and finite")


def _validate_limit(field_name: str, value: int, maximum: int) -> None:
    if value <= 0 or value > maximum:
        raise AgentDataConfigurationError(f"{field_name} must be between 1 and {maximum}")


def _parse_positive_int(field_name: str, value: str) -> int:
    try:
        parsed = int(value)
    except ValueError as exc:
        raise AgentDataConfigurationError(f"{field_name} must be a positive integer") from exc
    _validate_positive_int(field_name, parsed)
    return parsed
