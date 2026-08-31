from __future__ import annotations

import os
from datetime import UTC, datetime
from typing import cast
from uuid import UUID

import pytest

from supplychain.agent import (
    CreateInvestigationRequest,
    HumanReviewDecision,
    HumanReviewStatus,
    InvestigationModel,
    InvestigationService,
    InvestigationStatus,
    SubmitHumanReviewRequest,
)
from supplychain.agent.data import AgentDataService
from supplychain.agent.evaluation.harness import (
    FakeAgentDataService,
    FakeInvestigationModel,
    _analysis,
    _event,
    _risk,
)
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


@pytest.mark.skipif(
    os.environ.get("SUPPLYCHAIN_RUN_POSTGRES_INTEGRATION") != "1"
    or not os.environ.get(AGENT_POSTGRES_DSN_ENV),
    reason="PostgreSQL integration test requires explicit opt-in and DSN",
)
def test_postgres_hitl_review_persists_across_service_instances() -> None:
    dsn = os.environ[AGENT_POSTGRES_DSN_ENV]
    investigation_id = UUID("33333333-3333-4333-8333-333333333333")
    thread_id = UUID("44444444-4444-4444-8444-444444444444")
    created_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    with PostgresCheckpointStore(dsn) as first_store:
        first_store.checkpointer.setup()
        first_service = _stage16_service(first_store.checkpointer)
        pending = first_service.run_investigation(
            CreateInvestigationRequest(
                supplier_id="SUP-000001",
                question="Synthetic HITL persistence smoke?",
                created_at=created_at,
                investigation_id=investigation_id,
                thread_id=thread_id,
            )
        )

    assert pending.status is InvestigationStatus.COMPLETED
    assert pending.human_review_status is HumanReviewStatus.PENDING
    assert pending.report is not None

    with PostgresCheckpointStore(dsn) as second_store:
        second_service = _stage16_service(second_store.checkpointer)
        resumed_pending = second_service.get_investigation_state(str(thread_id))
        approved = second_service.submit_review(
            SubmitHumanReviewRequest(
                investigation_id=investigation_id,
                thread_id=thread_id,
                decision=HumanReviewDecision.APPROVE,
                reviewer_id="reviewer-001",
                reviewed_at=created_at,
            )
        )

    assert resumed_pending.human_review_status is HumanReviewStatus.PENDING
    assert approved.human_review_status is HumanReviewStatus.APPROVED

    with PostgresCheckpointStore(dsn) as third_store:
        third_service = _stage16_service(third_store.checkpointer)
        final = third_service.get_investigation_state(str(thread_id))

    assert final.human_review_status is HumanReviewStatus.APPROVED
    assert final.human_review is not None
    assert final.human_review.reviewer_id == "reviewer-001"
    assert final.report == pending.report


@pytest.mark.skipif(
    os.environ.get("SUPPLYCHAIN_RUN_POSTGRES_INTEGRATION") != "1"
    or not os.environ.get(AGENT_POSTGRES_DSN_ENV),
    reason="PostgreSQL integration test requires explicit opt-in and DSN",
)
def test_postgres_hitl_rejection_persists_across_service_instances() -> None:
    dsn = os.environ[AGENT_POSTGRES_DSN_ENV]
    investigation_id = UUID("55555555-5555-4555-8555-555555555555")
    thread_id = UUID("66666666-6666-4666-8666-666666666666")
    created_at = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

    with PostgresCheckpointStore(dsn) as first_store:
        first_store.checkpointer.setup()
        first_service = _stage16_service(first_store.checkpointer)
        pending = first_service.run_investigation(
            CreateInvestigationRequest(
                supplier_id="SUP-000001",
                question="Synthetic HITL rejection persistence smoke?",
                created_at=created_at,
                investigation_id=investigation_id,
                thread_id=thread_id,
            )
        )

    with PostgresCheckpointStore(dsn) as second_store:
        second_service = _stage16_service(second_store.checkpointer)
        rejected = second_service.submit_review(
            SubmitHumanReviewRequest(
                investigation_id=investigation_id,
                thread_id=thread_id,
                decision=HumanReviewDecision.REJECT,
                reviewer_id="reviewer-001",
                reviewed_at=created_at,
                reason="Recommendation requires manual operations follow-up.",
            )
        )

    assert pending.human_review_status is HumanReviewStatus.PENDING
    assert rejected.human_review_status is HumanReviewStatus.REJECTED

    with PostgresCheckpointStore(dsn) as third_store:
        third_service = _stage16_service(third_store.checkpointer)
        final = third_service.get_investigation_state(str(thread_id))

    assert final.human_review_status is HumanReviewStatus.REJECTED
    assert final.human_review is not None
    assert final.human_review.reason == "Recommendation requires manual operations follow-up."
    assert final.report == pending.report


def _stage16_service(checkpointer: object) -> InvestigationService:
    return InvestigationService(
        checkpointer=checkpointer,  # type: ignore[arg-type]
        data_service=cast(
            AgentDataService,
            FakeAgentDataService(
                risk=_risk(evidence_keys=("a" * 64,)),
                evidence=(_event(),),
            ),
        ),
        model=cast(
            InvestigationModel,
            FakeInvestigationModel(_analysis(evidence_keys=("a" * 64,))),
        ),
        now=lambda: datetime(2026, 8, 29, 12, 0, tzinfo=UTC),
    )
