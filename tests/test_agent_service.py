from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from langgraph.checkpoint.memory import InMemorySaver

from supplychain.agent import (
    AgentConfigurationError,
    AgentPersistenceError,
    CreateInvestigationRequest,
    InvestigationNotFoundError,
    InvestigationService,
    InvestigationStatus,
)
from supplychain.agent.persistence import PostgresCheckpointStore

CREATED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
INVESTIGATION_ID = UUID("11111111-1111-4111-8111-111111111111")
THREAD_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_create_investigation_generates_distinct_ids() -> None:
    service = InvestigationService(checkpointer=InMemorySaver())

    first = service.create_investigation(
        CreateInvestigationRequest(supplier_id="SUP-000001", question="First?")
    )
    second = service.create_investigation(
        CreateInvestigationRequest(supplier_id="SUP-000001", question="Second?")
    )

    assert first.investigation_id != second.investigation_id
    assert first.thread_id != second.thread_id
    assert first.status is InvestigationStatus.READY


def test_create_investigation_supports_explicit_ids_for_deterministic_tests() -> None:
    service = InvestigationService(checkpointer=InMemorySaver())

    created = service.create_investigation(
        CreateInvestigationRequest(
            supplier_id="SUP-000001",
            question="Why?",
            created_at=CREATED_AT,
            investigation_id=INVESTIGATION_ID,
            thread_id=THREAD_ID,
        )
    )

    assert created.investigation_id == INVESTIGATION_ID
    assert created.thread_id == THREAD_ID
    assert created.created_at == CREATED_AT
    assert created.updated_at == CREATED_AT


def test_get_unknown_investigation_raises_not_found() -> None:
    service = InvestigationService(checkpointer=InMemorySaver())

    with pytest.raises(InvestigationNotFoundError):
        service.get_investigation_state(str(THREAD_ID))


def test_service_wraps_graph_creation_errors_without_dsn_leakage() -> None:
    class FailingGraph:
        def invoke(self, input: object, config: object) -> object:
            raise RuntimeError("postgresql://user:secret-password@localhost:5432/db")

        def get_state(self, config: object) -> object:
            raise AssertionError("not used")

    service = InvestigationService(
        checkpointer=InMemorySaver(),
        graph=FailingGraph(),  # type: ignore[arg-type]
    )

    with pytest.raises(AgentPersistenceError) as exc_info:
        service.create_investigation(
            CreateInvestigationRequest(
                supplier_id="SUP-000001",
                question="Why?",
                created_at=CREATED_AT,
            )
        )

    assert "secret-password" not in str(exc_info.value)
    assert "postgresql://" not in str(exc_info.value)


def test_postgres_dsn_configuration_rejects_blank_or_wrong_scheme() -> None:
    with pytest.raises(AgentConfigurationError):
        PostgresCheckpointStore("")
    with pytest.raises(AgentConfigurationError):
        PostgresCheckpointStore("sqlite:///agent.db")
