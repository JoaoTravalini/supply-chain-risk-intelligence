"""Contracts for LangGraph investigation state."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, NotRequired, TypedDict
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from supplychain.risk.models import EvidenceKey, SupplierId

Question = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True, strict=True)]
SafeIdentifier = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True, strict=True)]


class InvestigationStatus(StrEnum):
    """Stage 13 investigation lifecycle."""

    CREATED = "CREATED"
    READY = "READY"
    FAILED = "FAILED"


class StrictAgentModel(BaseModel):
    """Base class for immutable agent boundary models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class InvestigationIdentity(StrictAgentModel):
    """Distinct application and LangGraph checkpoint identities."""

    investigation_id: UUID = Field(default_factory=uuid4)
    thread_id: UUID = Field(default_factory=uuid4)


class CreateInvestigationRequest(StrictAgentModel):
    """Public input for creating a Stage 13 investigation."""

    supplier_id: SupplierId
    question: Question
    created_at: datetime | None = None
    investigation_id: UUID | None = None
    thread_id: UUID | None = None

    @field_validator("created_at")
    @classmethod
    def require_aware_created_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware_utc(value)


class InvestigationSnapshot(StrictAgentModel):
    """Persisted public investigation state returned by the service boundary."""

    investigation_id: UUID
    thread_id: UUID
    supplier_id: SupplierId
    question: Question
    status: InvestigationStatus
    created_at: datetime
    updated_at: datetime
    evidence_keys: tuple[EvidenceKey, ...] = ()
    error_message: str | None = None

    @field_validator("created_at", "updated_at")
    @classmethod
    def require_aware_timestamp(cls, value: datetime) -> datetime:
        return require_aware_utc(value)


class InvestigationState(TypedDict):
    """JSON-serializable LangGraph checkpoint state."""

    investigation_id: str
    thread_id: str
    supplier_id: str
    question: str
    status: str
    created_at: str
    updated_at: str
    evidence_keys: list[str]
    error_message: NotRequired[str | None]


def require_aware_utc(value: datetime) -> datetime:
    """Require a timezone-aware timestamp and normalize it to UTC."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("timestamp must be timezone-aware")
    return value.astimezone(UTC)


def utc_now() -> datetime:
    """Return the current operational timestamp in UTC."""

    return datetime.now(UTC)


def datetime_to_state(value: datetime) -> str:
    """Serialize UTC datetimes in deterministic Zulu form for checkpoints."""

    return require_aware_utc(value).isoformat().replace("+00:00", "Z")


def datetime_from_state(value: str) -> datetime:
    """Deserialize checkpoint timestamps into aware UTC datetimes."""

    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def snapshot_to_state(snapshot: InvestigationSnapshot) -> InvestigationState:
    """Convert a public snapshot into JSON-serializable LangGraph state."""

    return {
        "investigation_id": str(snapshot.investigation_id),
        "thread_id": str(snapshot.thread_id),
        "supplier_id": snapshot.supplier_id,
        "question": snapshot.question,
        "status": snapshot.status.value,
        "created_at": datetime_to_state(snapshot.created_at),
        "updated_at": datetime_to_state(snapshot.updated_at),
        "evidence_keys": list(snapshot.evidence_keys),
        "error_message": snapshot.error_message,
    }


def snapshot_from_state(state: InvestigationState | dict[str, object]) -> InvestigationSnapshot:
    """Validate persisted LangGraph state at the public boundary."""

    evidence_keys = state["evidence_keys"]
    if not isinstance(evidence_keys, Iterable) or isinstance(evidence_keys, str):
        raise ValueError("evidence_keys must be an iterable of strings")
    return InvestigationSnapshot(
        investigation_id=UUID(str(state["investigation_id"])),
        thread_id=UUID(str(state["thread_id"])),
        supplier_id=str(state["supplier_id"]),
        question=str(state["question"]),
        status=InvestigationStatus(str(state["status"])),
        created_at=datetime_from_state(str(state["created_at"])),
        updated_at=datetime_from_state(str(state["updated_at"])),
        evidence_keys=tuple(str(key) for key in evidence_keys),
        error_message=(
            None if state.get("error_message") is None else str(state.get("error_message"))
        ),
    )
