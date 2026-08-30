from __future__ import annotations

import os
from datetime import UTC, datetime
from uuid import UUID

import pytest

from supplychain.agent import CreateInvestigationRequest, InvestigationService
from supplychain.agent.persistence import AGENT_POSTGRES_DSN_ENV, PostgresCheckpointStore

pytestmark = pytest.mark.integration


@pytest.mark.skipif(
    os.environ.get("SUPPLYCHAIN_RUN_POSTGRES_INTEGRATION") != "1"
    or not os.environ.get(AGENT_POSTGRES_DSN_ENV),
    reason="PostgreSQL integration test requires explicit opt-in and DSN",
)
def test_postgres_checkpointer_persists_across_service_instances() -> None:
    dsn = os.environ[AGENT_POSTGRES_DSN_ENV]
    investigation_id = UUID("11111111-1111-4111-8111-111111111111")
    thread_id = UUID("22222222-2222-4222-8222-222222222222")
    created_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    with PostgresCheckpointStore(dsn) as first_store:
        first_store.checkpointer.setup()
        first_service = InvestigationService(checkpointer=first_store.checkpointer)
        created = first_service.create_investigation(
            CreateInvestigationRequest(
                supplier_id="SUP-000001",
                question="Synthetic persistence smoke?",
                created_at=created_at,
                investigation_id=investigation_id,
                thread_id=thread_id,
            )
        )

    with PostgresCheckpointStore(dsn) as second_store:
        second_service = InvestigationService(checkpointer=second_store.checkpointer)
        resumed = second_service.get_investigation_state(str(thread_id))

    assert resumed == created
