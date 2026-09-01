from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import cast

import pytest
from google.cloud import bigquery

from supplychain.agent.data import (
    AgentBigQueryConfig,
    AgentDataConfigurationError,
    GuardedBigQueryReader,
)
from supplychain.domain import Criticality, SupplierCategory
from supplychain.risk import RiskFactorFamily, RiskLevel
from supplychain.ui.data import (
    MAX_PORTFOLIO_LIMIT,
    PortfolioDataService,
    PortfolioSupplierRiskRow,
    assert_dashboard_sql_is_safe,
    filter_portfolio_rows,
    portfolio_summary,
    sorted_portfolio_rows,
)
from supplychain.ui.presentation import (
    highest_risk_rows,
    portfolio_table_rows,
    risk_level_distribution,
)

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class QueryCall:
    query: str
    job_config: bigquery.QueryJobConfig


class FakeQueryJob:
    def __init__(self, rows: tuple[object, ...], total_bytes_processed: int = 100) -> None:
        self._rows = rows
        self.total_bytes_processed = total_bytes_processed

    def result(self, timeout: float | None = None) -> tuple[object, ...]:
        return self._rows


class FakeBigQueryClient:
    def __init__(self, rows: tuple[object, ...], estimated_bytes: int = 100) -> None:
        self.rows = rows
        self.estimated_bytes = estimated_bytes
        self.calls: list[QueryCall] = []

    def query(self, query: str, *, job_config: object) -> FakeQueryJob:
        cfg = cast(bigquery.QueryJobConfig, job_config)
        self.calls.append(QueryCall(query=query, job_config=cfg))
        if cfg.dry_run:
            return FakeQueryJob((), self.estimated_bytes)
        return FakeQueryJob(self.rows, self.estimated_bytes)

    def close(self) -> None:
        pass


def test_portfolio_summary_filters_and_order_are_deterministic() -> None:
    rows = (
        portfolio_row(supplier_id="SUP-000002", risk_score=20.0, risk_level=RiskLevel.LOW),
        portfolio_row(supplier_id="SUP-000001", risk_score=80.0, risk_level=RiskLevel.CRITICAL),
        portfolio_row(supplier_id="SUP-000003", risk_score=80.0, risk_level=RiskLevel.CRITICAL),
    )

    sorted_rows = sorted_portfolio_rows(rows)
    summary = portfolio_summary(rows)
    filtered = filter_portfolio_rows(
        rows,
        risk_levels={RiskLevel.CRITICAL},
        categories=set(),
        countries={"US"},
    )

    assert [row.supplier_id for row in sorted_rows] == ["SUP-000001", "SUP-000003", "SUP-000002"]
    assert summary.total_suppliers == 3
    assert summary.average_risk_score == 60.0
    assert summary.highest_risk_score == 80.0
    assert summary.risk_level_counts[RiskLevel.CRITICAL] == 2
    assert [row.supplier_id for row in filtered] == ["SUP-000001", "SUP-000003"]


def test_portfolio_empty_state_and_presentation_rows_are_safe() -> None:
    summary = portfolio_summary(())

    assert summary.total_suppliers == 0
    assert summary.average_risk_score == 0.0
    assert risk_level_distribution(()) == {
        "LOW": 0,
        "MEDIUM": 0,
        "HIGH": 0,
        "CRITICAL": 0,
    }
    assert portfolio_table_rows(()) == []
    assert highest_risk_rows(()) == []


def test_portfolio_data_service_uses_guarded_static_select_and_bounds_results() -> None:
    client = FakeBigQueryClient((portfolio_bigquery_row("SUP-000001"),))
    config = AgentBigQueryConfig(project_id="supplychain-sentinel-test", max_bytes_billed=1_000)
    service = PortfolioDataService(config, reader=GuardedBigQueryReader(config, client=client))

    snapshot = service.get_current_portfolio(limit=10)

    assert len(snapshot.rows) == 1
    assert snapshot.rows[0].risk_score == 41.83
    assert snapshot.executions[0].operation_name == "get_current_portfolio"
    assert snapshot.executions[0].estimated_bytes_processed == 100
    assert snapshot.executions[0].maximum_bytes_billed == 1_000
    assert len(client.calls) == 2
    assert client.calls[0].job_config.dry_run is True
    assert client.calls[0].job_config.maximum_bytes_billed == 1_000
    assert client.calls[1].job_config.dry_run is False
    assert "supplychain_raw" not in client.calls[1].query.lower()
    assert client.calls[1].query.strip().lower().startswith("select")
    assert client.calls[1].job_config.query_parameters[0].name == "limit"


def test_portfolio_data_service_rejects_invalid_limit_and_unsafe_sql() -> None:
    client = FakeBigQueryClient(())
    config = AgentBigQueryConfig(project_id="supplychain-sentinel-test")
    service = PortfolioDataService(config, reader=GuardedBigQueryReader(config, client=client))

    with pytest.raises(AgentDataConfigurationError):
        service.get_current_portfolio(limit=0)
    with pytest.raises(AgentDataConfigurationError):
        service.get_current_portfolio(limit=MAX_PORTFOLIO_LIMIT + 1)
    with pytest.raises(AgentDataConfigurationError):
        assert_dashboard_sql_is_safe("DELETE FROM supplychain_mart.supplier_risk_current")
    with pytest.raises(AgentDataConfigurationError):
        assert_dashboard_sql_is_safe("SELECT * FROM supplychain_raw.canonical_events")


def portfolio_row(
    *,
    supplier_id: str,
    risk_score: float,
    risk_level: RiskLevel,
) -> PortfolioSupplierRiskRow:
    return PortfolioSupplierRiskRow(
        supplier_id=supplier_id,
        supplier_name=f"Supplier {supplier_id}",
        category=SupplierCategory.ELECTRONIC_COMPONENTS,
        criticality=Criticality.HIGH,
        country_code="US",
        region="WA",
        city="Seattle",
        annual_spend_usd=1_250_000,
        typical_lead_time_days=28,
        dependency_score=0.74,
        single_source=True,
        assessed_at=NOW,
        risk_score=risk_score,
        risk_level=risk_level,
        model_version="1.0.0",
        structural_score=83.66,
        weather_score=0.0,
        seismic_score=0.0,
        dominant_factor=RiskFactorFamily.STRUCTURAL,
        criticality_component=0.75,
        dependency_component=0.74,
        single_source_component=1.0,
        lead_time_component=0.08,
        relevant_weather_event_count=0,
        relevant_seismic_event_count=0,
        evidence_deduplication_keys=(),
    )


def portfolio_bigquery_row(supplier_id: str) -> dict[str, object]:
    return {
        "supplier_id": supplier_id,
        "name": "Synthetic Components North",
        "category": "electronic_components",
        "criticality": "HIGH",
        "country_code": "US",
        "region": "WA",
        "city": "Seattle",
        "annual_spend_usd": 1_250_000,
        "typical_lead_time_days": 28,
        "dependency_score": 0.74,
        "single_source": True,
        "assessed_at": NOW,
        "risk_score": 41.83,
        "risk_level": "MEDIUM",
        "model_version": "1.0.0",
        "structural_score": 83.66,
        "weather_score": 0.0,
        "seismic_score": 0.0,
        "dominant_factor": "STRUCTURAL",
        "criticality_component": 0.75,
        "dependency_component": 0.74,
        "single_source_component": 1.0,
        "lead_time_component": 0.08,
        "relevant_weather_event_count": 0,
        "relevant_seismic_event_count": 0,
        "evidence_deduplication_keys": [],
    }
