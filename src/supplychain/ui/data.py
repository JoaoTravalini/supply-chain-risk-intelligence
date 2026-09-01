"""Typed Streamlit dashboard read boundary."""

from __future__ import annotations

import json
import time
from collections.abc import Iterable, Mapping
from datetime import UTC, datetime
from importlib.resources import files

from google.cloud import bigquery
from pydantic import BaseModel, ConfigDict, Field, field_validator

from supplychain.agent.data import (
    AgentBigQueryConfig,
    AgentDataConfigurationError,
    AgentDataIntegrityError,
    GuardedBigQueryReader,
    QueryExecutionSummary,
    _QuerySpec,
    agent_bigquery_config_from_env,
)
from supplychain.domain import Criticality, SupplierCategory
from supplychain.observability import ObservabilityRuntime
from supplychain.observability.runtime import TelemetryOutcome, elapsed_ms
from supplychain.risk import RiskFactorFamily, RiskLevel
from supplychain.risk.models import EvidenceKey, RiskScore, SemanticVersion, SupplierId

DEFAULT_PORTFOLIO_LIMIT = 200
MAX_PORTFOLIO_LIMIT = 500


class StrictUiModel(BaseModel):
    """Base class for immutable UI presentation models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class PortfolioSupplierRiskRow(StrictUiModel):
    """One bounded portfolio row joined from CORE Supplier and MART risk data."""

    supplier_id: SupplierId
    supplier_name: str
    category: SupplierCategory
    criticality: Criticality
    country_code: str
    region: str
    city: str
    annual_spend_usd: int
    typical_lead_time_days: int
    dependency_score: float = Field(ge=0.0, le=1.0)
    single_source: bool
    assessed_at: datetime
    risk_score: RiskScore
    risk_level: RiskLevel
    model_version: SemanticVersion
    structural_score: RiskScore
    weather_score: RiskScore
    seismic_score: RiskScore
    dominant_factor: RiskFactorFamily
    criticality_component: float = Field(ge=0.0, le=1.0)
    dependency_component: float = Field(ge=0.0, le=1.0)
    single_source_component: float = Field(ge=0.0, le=1.0)
    lead_time_component: float = Field(ge=0.0, le=1.0)
    relevant_weather_event_count: int = Field(ge=0)
    relevant_seismic_event_count: int = Field(ge=0)
    evidence_deduplication_keys: tuple[EvidenceKey, ...]

    @field_validator("assessed_at")
    @classmethod
    def require_aware_assessed_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")
        return value.astimezone(UTC)


class PortfolioSummary(StrictUiModel):
    """Portfolio-level KPI values derived from the bounded snapshot."""

    total_suppliers: int = Field(ge=0)
    average_risk_score: float = Field(ge=0.0, le=100.0)
    highest_risk_score: float = Field(ge=0.0, le=100.0)
    risk_level_counts: dict[RiskLevel, int]


class PortfolioSnapshot(StrictUiModel):
    """Bounded portfolio data and safe query metadata."""

    rows: tuple[PortfolioSupplierRiskRow, ...]
    summary: PortfolioSummary
    executions: tuple[QueryExecutionSummary, ...]


class PortfolioDataService:
    """Read dashboard data through the existing guarded BigQuery reader."""

    def __init__(
        self,
        config: AgentBigQueryConfig,
        *,
        reader: GuardedBigQueryReader,
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._config = config
        self._reader = reader
        self._observability = observability or ObservabilityRuntime.disabled()

    @property
    def executions(self) -> tuple[QueryExecutionSummary, ...]:
        """Return safe BigQuery execution summaries."""

        return self._reader.executions

    def get_current_portfolio(
        self,
        *,
        limit: int = DEFAULT_PORTFOLIO_LIMIT,
    ) -> PortfolioSnapshot:
        """Read a bounded current supplier-risk portfolio snapshot."""

        _validate_portfolio_limit(limit)
        started_at = time.perf_counter()
        with self._observability.span(
            "supplychain.portfolio.load",
            attributes={"component": "portfolio", "operation": "get_current_portfolio"},
        ) as span:
            try:
                rows = self._reader.read(_current_portfolio_spec(self._config, limit))
                if len(rows) > limit:
                    raise AgentDataIntegrityError("Portfolio query exceeded requested limit")
                portfolio_rows = tuple(_portfolio_row_from_bigquery(row) for row in rows)
                snapshot = PortfolioSnapshot(
                    rows=portfolio_rows,
                    summary=portfolio_summary(portfolio_rows),
                    executions=self._reader.executions,
                )
                self._observability.record_operation(
                    component="portfolio",
                    operation="get_current_portfolio",
                    outcome=TelemetryOutcome.SUCCESS,
                    duration_ms=elapsed_ms(started_at),
                )
                self._observability.set_span_status(span, TelemetryOutcome.SUCCESS)
                return snapshot
            except Exception:
                self._observability.record_operation(
                    component="portfolio",
                    operation="get_current_portfolio",
                    outcome=TelemetryOutcome.FAILURE,
                    duration_ms=elapsed_ms(started_at),
                )
                self._observability.set_span_status(span, TelemetryOutcome.FAILURE)
                raise


def portfolio_data_service_from_env(
    observability: ObservabilityRuntime | None = None,
) -> PortfolioDataService:
    """Create the dashboard data service from existing BigQuery environment config."""

    config = agent_bigquery_config_from_env()
    runtime = observability or ObservabilityRuntime.disabled()
    return PortfolioDataService(
        config,
        reader=GuardedBigQueryReader(config, observability=runtime),
        observability=runtime,
    )


def portfolio_summary(rows: tuple[PortfolioSupplierRiskRow, ...]) -> PortfolioSummary:
    """Compute deterministic KPIs from the bounded portfolio snapshot."""

    if not rows:
        return PortfolioSummary(
            total_suppliers=0,
            average_risk_score=0.0,
            highest_risk_score=0.0,
            risk_level_counts={level: 0 for level in RiskLevel},
        )
    total_score = sum(row.risk_score for row in rows)
    counts = {level: 0 for level in RiskLevel}
    for row in rows:
        counts[row.risk_level] += 1
    return PortfolioSummary(
        total_suppliers=len(rows),
        average_risk_score=round(total_score / len(rows), 2),
        highest_risk_score=max(row.risk_score for row in rows),
        risk_level_counts=counts,
    )


def sorted_portfolio_rows(
    rows: Iterable[PortfolioSupplierRiskRow],
) -> tuple[PortfolioSupplierRiskRow, ...]:
    """Sort portfolio rows deterministically by risk, then Supplier ID."""

    return tuple(sorted(rows, key=lambda row: (-row.risk_score, row.supplier_id)))


def filter_portfolio_rows(
    rows: Iterable[PortfolioSupplierRiskRow],
    *,
    risk_levels: set[RiskLevel],
    categories: set[SupplierCategory],
    countries: set[str],
) -> tuple[PortfolioSupplierRiskRow, ...]:
    """Apply client-side filters to an already bounded portfolio snapshot."""

    return sorted_portfolio_rows(
        row
        for row in rows
        if (not risk_levels or row.risk_level in risk_levels)
        and (not categories or row.category in categories)
        and (not countries or row.country_code in countries)
    )


def _current_portfolio_spec(config: AgentBigQueryConfig, limit: int) -> _QuerySpec:
    return _QuerySpec(
        name="get_current_portfolio",
        sql=_sql("current_portfolio").format(
            core_suppliers_table=config.core_suppliers_table,
            mart_supplier_risk_current_table=config.mart_supplier_risk_current_table,
        ),
        parameters=(bigquery.ScalarQueryParameter("limit", "INT64", limit),),
        max_result_rows=limit,
    )


def _portfolio_row_from_bigquery(row: object) -> PortfolioSupplierRiskRow:
    return PortfolioSupplierRiskRow(
        supplier_id=str(_row_value(row, "supplier_id")),
        supplier_name=str(_row_value(row, "name")),
        category=SupplierCategory(str(_row_value(row, "category"))),
        criticality=Criticality(str(_row_value(row, "criticality"))),
        country_code=str(_row_value(row, "country_code")),
        region=str(_row_value(row, "region")),
        city=str(_row_value(row, "city")),
        annual_spend_usd=_int_value(row, "annual_spend_usd"),
        typical_lead_time_days=_int_value(row, "typical_lead_time_days"),
        dependency_score=_float_value(row, "dependency_score"),
        single_source=bool(_row_value(row, "single_source")),
        assessed_at=_require_aware_utc(_row_value(row, "assessed_at")),
        risk_score=_float_value(row, "risk_score"),
        risk_level=RiskLevel(str(_row_value(row, "risk_level"))),
        model_version=str(_row_value(row, "model_version")),
        structural_score=_float_value(row, "structural_score"),
        weather_score=_float_value(row, "weather_score"),
        seismic_score=_float_value(row, "seismic_score"),
        dominant_factor=RiskFactorFamily(str(_row_value(row, "dominant_factor"))),
        criticality_component=_float_value(row, "criticality_component"),
        dependency_component=_float_value(row, "dependency_component"),
        single_source_component=_float_value(row, "single_source_component"),
        lead_time_component=_float_value(row, "lead_time_component"),
        relevant_weather_event_count=_int_value(row, "relevant_weather_event_count"),
        relevant_seismic_event_count=_int_value(row, "relevant_seismic_event_count"),
        evidence_deduplication_keys=_json_array(row, "evidence_deduplication_keys"),
    )


def _sql(name: str) -> str:
    return (files("supplychain.ui.sql") / f"{name}.sql").read_text(encoding="utf-8").strip()


def _json_array(row: object, name: str) -> tuple[str, ...]:
    value = _row_value(row, name)
    try:
        decoded = json.loads(value) if isinstance(value, str) else value
    except json.JSONDecodeError as exc:
        raise AgentDataIntegrityError("JSON field is malformed") from exc
    if not isinstance(decoded, list):
        raise AgentDataIntegrityError("JSON field is not an array")
    return tuple(str(item) for item in decoded)


def _row_value(row: object, name: str) -> object:
    if isinstance(row, Mapping):
        return row[name]
    return getattr(row, name)


def _int_value(row: object, name: str) -> int:
    value = _row_value(row, name)
    if isinstance(value, int):
        return value
    if isinstance(value, str):
        return int(value)
    raise AgentDataIntegrityError("integer field has invalid type")


def _float_value(row: object, name: str) -> float:
    value = _row_value(row, name)
    if isinstance(value, int | float):
        return float(value)
    if isinstance(value, str):
        return float(value)
    raise AgentDataIntegrityError("numeric field has invalid type")


def _require_aware_utc(value: object) -> datetime:
    if not isinstance(value, datetime):
        raise AgentDataIntegrityError("timestamp field is not a datetime")
    if value.tzinfo is None or value.utcoffset() is None:
        raise AgentDataIntegrityError("timestamp field is not timezone-aware")
    return value.astimezone(UTC)


def _validate_portfolio_limit(limit: int) -> None:
    if limit <= 0 or limit > MAX_PORTFOLIO_LIMIT:
        raise AgentDataConfigurationError(
            f"portfolio limit must be between 1 and {MAX_PORTFOLIO_LIMIT}"
        )


def assert_dashboard_sql_is_safe(sql: str) -> None:
    """Validate dashboard SQL catalog entries in tests and at construction time."""

    normalized = sql.strip().lower()
    if not normalized.startswith("select"):
        raise AgentDataConfigurationError("dashboard SQL must be SELECT-only")
    forbidden = ("supplychain_raw", "insert ", "update ", "delete ", "merge ", "truncate ")
    if any(token in normalized for token in forbidden):
        raise AgentDataConfigurationError("dashboard SQL contains a forbidden operation")


assert_dashboard_sql_is_safe(_sql("current_portfolio"))
