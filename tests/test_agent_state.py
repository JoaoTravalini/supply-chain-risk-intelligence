from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

import pytest
from pydantic import ValidationError

from supplychain.agent import (
    CreateInvestigationRequest,
    InvestigationIdentity,
    InvestigationSnapshot,
    InvestigationStatus,
)
from supplychain.agent.models import (
    datetime_to_state,
    snapshot_from_state,
    snapshot_to_state,
)

CREATED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
INVESTIGATION_ID = UUID("11111111-1111-4111-8111-111111111111")
THREAD_ID = UUID("22222222-2222-4222-8222-222222222222")


def test_investigation_identity_accepts_uuid_values() -> None:
    identity = InvestigationIdentity(
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
    )

    assert identity.investigation_id == INVESTIGATION_ID
    assert identity.thread_id == THREAD_ID


def test_investigation_identity_rejects_invalid_ids() -> None:
    with pytest.raises(ValidationError):
        InvestigationIdentity.model_validate(
            {"investigation_id": "not-a-uuid", "thread_id": str(THREAD_ID)}
        )


def test_create_request_validates_supplier_and_question() -> None:
    request = CreateInvestigationRequest(
        supplier_id="SUP-000001",
        question="  What changed?  ",
        created_at=CREATED_AT,
    )

    assert request.question == "What changed?"


@pytest.mark.parametrize("supplier_id", ["", "supplier-1", "SUP-ABCDEF"])
def test_create_request_rejects_invalid_supplier_id(supplier_id: str) -> None:
    with pytest.raises(ValidationError):
        CreateInvestigationRequest(supplier_id=supplier_id, question="What changed?")


@pytest.mark.parametrize("question", ["", "   "])
def test_create_request_rejects_blank_question(question: str) -> None:
    with pytest.raises(ValidationError):
        CreateInvestigationRequest(supplier_id="SUP-000001", question=question)


def test_create_request_rejects_naive_timestamp() -> None:
    with pytest.raises(ValidationError):
        CreateInvestigationRequest(
            supplier_id="SUP-000001",
            question="What changed?",
            created_at=datetime(2026, 8, 29, 12, 0),
        )


def test_explicit_status_lifecycle() -> None:
    assert [status.value for status in InvestigationStatus] == [
        "CREATED",
        "READY",
        "COMPLETED",
        "FAILED",
    ]


def test_state_serialization_is_json_compatible_and_safe() -> None:
    snapshot = InvestigationSnapshot(
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
        supplier_id="SUP-000001",
        question="What changed?",
        status=InvestigationStatus.READY,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        evidence_keys=("0" * 64,),
    )

    state = snapshot_to_state(snapshot)
    restored = snapshot_from_state(state)

    assert state == {
        "investigation_id": str(INVESTIGATION_ID),
        "thread_id": str(THREAD_ID),
        "supplier_id": "SUP-000001",
        "question": "What changed?",
        "status": "READY",
        "created_at": "2026-08-29T12:00:00Z",
        "updated_at": "2026-08-29T12:00:00Z",
        "evidence_keys": ["0" * 64],
        "supplier_profile": None,
        "current_risk": None,
        "risk_history": [],
        "evidence": [],
        "report": None,
        "error_code": None,
        "error_message": None,
        "provider_failure_category": None,
        "provider_exception_class": None,
        "provider_status_code": None,
    }
    assert restored == snapshot
    assert "client" not in state
    assert "credentials" not in state
    assert "checkpointer" not in state


def test_datetime_state_serialization_normalizes_to_utc() -> None:
    local_time = datetime.fromisoformat("2026-08-29T09:00:00-03:00")

    assert datetime_to_state(local_time) == "2026-08-29T12:00:00Z"
