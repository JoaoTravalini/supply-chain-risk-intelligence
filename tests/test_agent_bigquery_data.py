from __future__ import annotations

from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, cast

import pytest
from google.api_core.exceptions import GoogleAPICallError
from google.cloud import bigquery
from pydantic import ValidationError

from supplychain.agent import (
    DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED,
    DEFAULT_RISK_HISTORY_LIMIT,
    MAX_EVIDENCE_KEYS,
    AgentBigQueryConfig,
    AgentDataConfigurationError,
    AgentDataIntegrityError,
    AgentDataNotFoundError,
    AgentDataQueryError,
    AgentDataService,
    GuardedBigQueryReader,
    QueryBudgetExceededError,
    RiskEvidenceInput,
    RiskHistoryInput,
    SupplierLookupInput,
    agent_bigquery_config_from_env,
    approved_agent_data_tools,
)
from supplychain.contracts import EventType

ASSESSED_AT = datetime(2026, 8, 28, 16, 20, tzinfo=UTC)
EVENT_TIME = datetime(2026, 8, 28, 15, 20, tzinfo=UTC)
EVIDENCE_KEY = "a" * 64
SECOND_EVIDENCE_KEY = "b" * 64


class FakeQueryJob:
    def __init__(
        self,
        *,
        rows: Sequence[Mapping[str, object]] = (),
        total_bytes_processed: int = 0,
        failure: Exception | None = None,
    ) -> None:
        self.rows = tuple(rows)
        self.total_bytes_processed = total_bytes_processed
        self.failure = failure
        self.result_timeouts: list[float | None] = []

    def result(self, timeout: float | None = None) -> object:
        self.result_timeouts.append(timeout)
        if self.failure is not None:
            raise self.failure
        return self.rows


@dataclass(frozen=True, slots=True)
class QueryCall:
    query: str
    job_config: bigquery.QueryJobConfig


class FakeBigQueryClient:
    def __init__(
        self,
        jobs: Sequence[FakeQueryJob],
        *,
        query_failure: Exception | None = None,
    ) -> None:
        self.jobs = list(jobs)
        self.query_failure = query_failure
        self.calls: list[QueryCall] = []
        self.closed = False

    def query(self, query: str, *, job_config: object) -> FakeQueryJob:
        self.calls.append(
            QueryCall(query=query, job_config=cast(bigquery.QueryJobConfig, job_config))
        )
        if self.query_failure is not None:
            raise self.query_failure
        return self.jobs.pop(0)

    def close(self) -> None:
        self.closed = True


def config(**overrides: object) -> AgentBigQueryConfig:
    data = {
        "project_id": "supplychain-local",
        "max_bytes_billed": 100,
        "query_timeout_seconds": 7.0,
    }
    data.update(overrides)
    return AgentBigQueryConfig(**cast(Any, data))


def service(client: FakeBigQueryClient, cfg: AgentBigQueryConfig | None = None) -> AgentDataService:
    active_config = cfg or config()
    return AgentDataService(
        active_config, reader=GuardedBigQueryReader(active_config, client=client)
    )


def supplier_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
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
    row.update(overrides)
    return row


def risk_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "model_version": "1.0.0",
        "supplier_id": "SUP-000001",
        "assessed_at": ASSESSED_AT,
        "risk_score": 41.83,
        "risk_level": "MEDIUM",
        "structural_score": 83.66,
        "weather_score": 0.0,
        "seismic_score": 0.0,
        "criticality_component": 1.0,
        "dependency_component": 0.85,
        "single_source_component": 1.0,
        "lead_time_component": 0.19,
        "relevant_weather_event_count": 0,
        "relevant_seismic_event_count": 0,
        "evidence_deduplication_keys": [],
        "dominant_factor": "STRUCTURAL",
    }
    row.update(overrides)
    return row


def event_row(**overrides: object) -> dict[str, object]:
    row: dict[str, object] = {
        "event_id": "5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10",
        "event_type": EventType.WEATHER_OBSERVATION_RECORDED.value,
        "schema_version": "1.0.0",
        "event_time": EVENT_TIME,
        "ingested_at": EVENT_TIME + timedelta(minutes=1),
        "source_provider": "synthetic-weather",
        "source_endpoint": "synthetic://weather",
        "source_event_id": "weather-001",
        "source_request_id": "request-001",
        "entity_type": "supplier",
        "entity_id": "SUP-000001",
        "location_country_code": "US",
        "location_region": "WA",
        "correlation_id": "corr-001",
        "producer": "agent-test",
        "producer_version": "1.0.0",
        "deduplication_key": EVIDENCE_KEY,
        "payload": {"latitude": 47.6062, "longitude": -122.3321},
    }
    row.update(overrides)
    return row


def actual_calls(client: FakeBigQueryClient) -> list[QueryCall]:
    return [call for call in client.calls if not call.job_config.dry_run]


def dry_run_calls(client: FakeBigQueryClient) -> list[QueryCall]:
    return [call for call in client.calls if call.job_config.dry_run]


def test_config_validates_required_values(monkeypatch: pytest.MonkeyPatch) -> None:
    cfg = config()

    assert cfg.project_id == "supplychain-local"
    assert cfg.max_bytes_billed == 100
    assert cfg.default_history_limit == DEFAULT_RISK_HISTORY_LIMIT

    monkeypatch.setenv("SUPPLYCHAIN_GCP_PROJECT_ID", "supplychain-local")
    monkeypatch.setenv("SUPPLYCHAIN_AGENT_BIGQUERY_MAX_BYTES_BILLED", "123")
    assert agent_bigquery_config_from_env().max_bytes_billed == 123


@pytest.mark.parametrize(
    "kwargs",
    [
        {"project_id": ""},
        {"project_id": "local", "max_bytes_billed": 0},
        {"project_id": "local", "max_bytes_billed": -1},
        {"project_id": "local", "query_timeout_seconds": 0.0},
        {"project_id": "local", "default_history_limit": 101},
        {"project_id": "local", "max_history_limit": 101},
        {"project_id": "local", "max_evidence_keys": 0},
    ],
)
def test_config_rejects_invalid_values(kwargs: dict[str, object]) -> None:
    with pytest.raises(AgentDataConfigurationError):
        AgentBigQueryConfig(**cast(Any, kwargs))


def test_missing_project_id_env_is_rejected(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.delenv("SUPPLYCHAIN_GCP_PROJECT_ID", raising=False)

    with pytest.raises(AgentDataConfigurationError):
        agent_bigquery_config_from_env()


def test_query_guardrails_apply_dry_run_standard_sql_parameters_budget_and_timeout() -> None:
    client = FakeBigQueryClient(
        [FakeQueryJob(total_bytes_processed=99), FakeQueryJob(rows=[supplier_row()])]
    )

    result = service(client).get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))

    assert result.supplier_id == "SUP-000001"
    assert len(client.calls) == 2
    assert dry_run_calls(client)[0].job_config.use_legacy_sql is False
    assert dry_run_calls(client)[0].job_config.use_query_cache is False
    assert actual_calls(client)[0].job_config.use_legacy_sql is False
    assert actual_calls(client)[0].job_config.maximum_bytes_billed == 100
    assert client.jobs == []
    assert client.calls[0].job_config.query_parameters[0].name == "supplier_id"
    assert "SUP-000001" not in client.calls[0].query
    assert "supplychain_raw" not in client.calls[0].query


@pytest.mark.parametrize(
    ("estimated", "runs_actual"),
    [(99, True), (100, True), (101, False)],
)
def test_cost_budget_boundary(estimated: int, runs_actual: bool) -> None:
    jobs = [FakeQueryJob(total_bytes_processed=estimated)]
    if runs_actual:
        jobs.append(FakeQueryJob(rows=[supplier_row()]))
    client = FakeBigQueryClient(jobs)
    data_service = service(client)

    if runs_actual:
        data_service.get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))
        assert len(client.calls) == 2
    else:
        with pytest.raises(QueryBudgetExceededError) as exc_info:
            data_service.get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))
        assert "estimated_bytes=101" in str(exc_info.value)
        assert "allowed_bytes=100" in str(exc_info.value)
        assert "SELECT" not in str(exc_info.value)
        assert len(client.calls) == 1


def test_dry_run_failure_prevents_actual_query_and_sanitizes_error() -> None:
    client = FakeBigQueryClient(
        [],
        query_failure=GoogleAPICallError("SELECT token secret payload"),  # type: ignore[no-untyped-call]
    )

    with pytest.raises(AgentDataQueryError) as exc_info:
        service(client).get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))

    assert len(client.calls) == 1
    assert "SELECT" not in str(exc_info.value)
    assert "secret" not in str(exc_info.value)
    assert "payload" not in str(exc_info.value)


def test_no_arbitrary_sql_api_exists() -> None:
    data_service = service(FakeBigQueryClient([]))

    assert not hasattr(data_service, "execute_sql")
    assert not hasattr(data_service, "query")
    assert not hasattr(data_service, "run_sql")
    assert set(approved_agent_data_tools(data_service)) == {
        "get_supplier_profile",
        "get_current_supplier_risk",
        "get_supplier_risk_history",
        "get_risk_evidence",
    }


def test_supplier_profile_maps_one_row_and_enforces_cardinality() -> None:
    client = FakeBigQueryClient(
        [FakeQueryJob(total_bytes_processed=1), FakeQueryJob(rows=[supplier_row()])]
    )

    profile = service(client).get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))

    assert profile.name == "Synthetic Components North"

    not_found = FakeBigQueryClient([FakeQueryJob(), FakeQueryJob(rows=[])])
    with pytest.raises(AgentDataNotFoundError):
        service(not_found).get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))

    duplicate = FakeBigQueryClient(
        [FakeQueryJob(), FakeQueryJob(rows=[supplier_row(), supplier_row()])]
    )
    with pytest.raises(AgentDataIntegrityError):
        service(duplicate).get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))


def test_current_risk_maps_authoritative_mart_row_without_risk_engine(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fail(*args: object, **kwargs: object) -> object:
        raise AssertionError("risk engine must not be called")

    monkeypatch.setattr("supplychain.risk.SupplierRiskEngine.assess", fail)
    client = FakeBigQueryClient([FakeQueryJob(), FakeQueryJob(rows=[risk_row()])])

    risk = service(client).get_current_supplier_risk(SupplierLookupInput(supplier_id="SUP-000001"))

    assert risk.risk_score == 41.83
    assert risk.assessed_at == ASSESSED_AT
    assert "supplychain_mart.supplier_risk_current" in actual_calls(client)[0].query


def test_current_risk_not_found_and_duplicates_are_explicit() -> None:
    not_found = FakeBigQueryClient([FakeQueryJob(), FakeQueryJob(rows=[])])
    with pytest.raises(AgentDataNotFoundError):
        service(not_found).get_current_supplier_risk(SupplierLookupInput(supplier_id="SUP-000001"))

    duplicate = FakeBigQueryClient([FakeQueryJob(), FakeQueryJob(rows=[risk_row(), risk_row()])])
    with pytest.raises(AgentDataIntegrityError):
        service(duplicate).get_current_supplier_risk(SupplierLookupInput(supplier_id="SUP-000001"))


def test_history_default_explicit_limits_ordering_and_bounds() -> None:
    rows = [
        risk_row(assessed_at=ASSESSED_AT),
        risk_row(assessed_at=ASSESSED_AT - timedelta(days=1), risk_score=30.0),
    ]
    client = FakeBigQueryClient([FakeQueryJob(), FakeQueryJob(rows=rows)])

    history = service(client).get_supplier_risk_history(RiskHistoryInput(supplier_id="SUP-000001"))

    assert len(history) == 2
    assert history[0].assessed_at > history[1].assessed_at
    query = actual_calls(client)[0].query
    assert "ORDER BY assessed_at DESC" in query
    assert "LIMIT @limit" in query
    assert [param.name for param in actual_calls(client)[0].job_config.query_parameters] == [
        "supplier_id",
        "limit",
    ]


@pytest.mark.parametrize("limit", [0, -1, 101])
def test_history_rejects_invalid_limits(limit: int) -> None:
    with pytest.raises(ValidationError):
        RiskHistoryInput(supplier_id="SUP-000001", limit=limit)


def test_history_fails_if_rows_exceed_requested_limit() -> None:
    client = FakeBigQueryClient([FakeQueryJob(), FakeQueryJob(rows=[risk_row(), risk_row()])])

    with pytest.raises(AgentDataIntegrityError):
        service(client).get_supplier_risk_history(
            RiskHistoryInput(supplier_id="SUP-000001", limit=1)
        )


def test_evidence_empty_returns_without_bigquery_query() -> None:
    client = FakeBigQueryClient([])

    evidence = service(client).get_risk_evidence(RiskEvidenceInput(evidence_deduplication_keys=()))

    assert evidence == ()
    assert client.calls == []


def test_evidence_deduplicates_input_and_maps_canonical_events() -> None:
    client = FakeBigQueryClient(
        [
            FakeQueryJob(total_bytes_processed=10),
            FakeQueryJob(
                rows=[
                    event_row(deduplication_key=EVIDENCE_KEY),
                    event_row(
                        event_id="6f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f11",
                        deduplication_key=SECOND_EVIDENCE_KEY,
                        event_time=EVENT_TIME + timedelta(minutes=1),
                    ),
                ]
            ),
        ]
    )

    evidence = service(client).get_risk_evidence(
        RiskEvidenceInput(
            evidence_deduplication_keys=(SECOND_EVIDENCE_KEY, EVIDENCE_KEY, EVIDENCE_KEY)
        )
    )

    assert [event.metadata.deduplication_key for event in evidence] == [
        EVIDENCE_KEY,
        SECOND_EVIDENCE_KEY,
    ]
    params = actual_calls(client)[0].job_config.query_parameters
    assert cast(Any, params[0]).values == [EVIDENCE_KEY, SECOND_EVIDENCE_KEY]
    assert "event_id IN" not in actual_calls(client)[0].query
    assert "ORDER BY event_time ASC, deduplication_key ASC" in actual_calls(client)[0].query


def test_evidence_rejects_oversized_request() -> None:
    keys = tuple(f"{index:064x}" for index in range(MAX_EVIDENCE_KEYS + 1))

    with pytest.raises(ValidationError):
        RiskEvidenceInput(evidence_deduplication_keys=keys)


def test_evidence_malformed_row_fails_explicitly() -> None:
    client = FakeBigQueryClient(
        [FakeQueryJob(), FakeQueryJob(rows=[event_row(payload="not-json-object")])]
    )

    with pytest.raises(AgentDataIntegrityError):
        service(client).get_risk_evidence(
            RiskEvidenceInput(evidence_deduplication_keys=(EVIDENCE_KEY,))
        )


def test_public_query_errors_do_not_expose_sql_payload_or_credentials() -> None:
    client = FakeBigQueryClient(
        [
            FakeQueryJob(),
            FakeQueryJob(
                failure=RuntimeError("SELECT * FROM secret.table password=abc payload={sensitive}")
            ),
        ]
    )

    with pytest.raises(AgentDataQueryError) as exc_info:
        service(client).get_supplier_profile(SupplierLookupInput(supplier_id="SUP-000001"))

    error_text = str(exc_info.value)
    assert "SELECT" not in error_text
    assert "password" not in error_text
    assert "payload" not in error_text
    assert "secret" not in error_text


def test_default_cost_budget_constant_is_precise() -> None:
    assert DEFAULT_AGENT_BIGQUERY_MAX_BYTES_BILLED == 100 * 1024 * 1024
