from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver

from supplychain.agent import (
    CreateInvestigationRequest,
    InvestigationService,
    InvestigationStatus,
)

CREATED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
FIRST_INVESTIGATION_ID = UUID("11111111-1111-4111-8111-111111111111")
FIRST_THREAD_ID = UUID("22222222-2222-4222-8222-222222222222")
SECOND_INVESTIGATION_ID = UUID("33333333-3333-4333-8333-333333333333")
SECOND_THREAD_ID = UUID("44444444-4444-4444-8444-444444444444")


def make_request(
    *,
    investigation_id: UUID = FIRST_INVESTIGATION_ID,
    thread_id: UUID = FIRST_THREAD_ID,
    question: str = "Why is this supplier elevated?",
) -> CreateInvestigationRequest:
    return CreateInvestigationRequest(
        supplier_id="SUP-000001",
        question=question,
        created_at=CREATED_AT,
        investigation_id=investigation_id,
        thread_id=thread_id,
    )


def test_in_memory_checkpointer_persists_latest_state_for_same_thread() -> None:
    saver = InMemorySaver()
    service = InvestigationService(checkpointer=saver)

    created = service.create_investigation(make_request())
    persisted = service.get_investigation_state(str(FIRST_THREAD_ID))

    assert created == persisted
    assert persisted.status is InvestigationStatus.READY


def test_in_memory_checkpointer_isolates_different_threads() -> None:
    service = InvestigationService(checkpointer=InMemorySaver())

    first = service.create_investigation(make_request())
    second = service.create_investigation(
        make_request(
            investigation_id=SECOND_INVESTIGATION_ID,
            thread_id=SECOND_THREAD_ID,
            question="What changed in this separate investigation?",
        )
    )

    assert service.get_investigation_state(str(first.thread_id)).question == first.question
    assert service.get_investigation_state(str(second.thread_id)).question == second.question
    assert first.thread_id != second.thread_id
    assert first.supplier_id == second.supplier_id


def test_repeated_read_does_not_mutate_checkpoint_state() -> None:
    service = InvestigationService(checkpointer=InMemorySaver())
    service.create_investigation(make_request())

    first_read = service.get_investigation_state(str(FIRST_THREAD_ID))
    second_read = service.get_investigation_state(str(FIRST_THREAD_ID))

    assert first_read == second_read


def test_no_global_graph_or_checkpointer_leak_between_services() -> None:
    first_service = InvestigationService(checkpointer=InMemorySaver())
    second_service = InvestigationService(checkpointer=InMemorySaver())
    first_service.create_investigation(make_request())

    from supplychain.agent import InvestigationNotFoundError

    try:
        second_service.get_investigation_state(str(FIRST_THREAD_ID))
    except InvestigationNotFoundError:
        pass
    else:
        raise AssertionError("state leaked between independent checkpointers")
