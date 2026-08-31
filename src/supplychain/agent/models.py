"""Contracts for LangGraph investigation state."""

from __future__ import annotations

import json
from collections.abc import Iterable
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, NotRequired, TypedDict
from uuid import UUID, uuid4

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    StringConstraints,
    field_validator,
    model_validator,
)

from supplychain.agent.errors import ProviderFailureCategory
from supplychain.agent.reports import InvestigationReport
from supplychain.risk.models import EvidenceKey, RiskLevel, RiskScore, SupplierId

Question = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2_000, strip_whitespace=True, strict=True),
]
SafeIdentifier = Annotated[str, StringConstraints(min_length=1, strip_whitespace=True, strict=True)]
ReviewComment = Annotated[
    str,
    StringConstraints(min_length=1, max_length=2_000, strip_whitespace=True, strict=True),
]


class InvestigationStatus(StrEnum):
    """Investigation lifecycle."""

    CREATED = "CREATED"
    READY = "READY"
    COMPLETED = "COMPLETED"
    FAILED = "FAILED"


class HumanReviewStatus(StrEnum):
    """Separate human review lifecycle for produced investigation reports."""

    NOT_REQUESTED = "NOT_REQUESTED"
    PENDING = "PENDING"
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"


class HumanReviewDecision(StrEnum):
    """Human decisions supported by Stage 16."""

    APPROVE = "APPROVE"
    REJECT = "REJECT"


class ValidationFailureCode(StrEnum):
    """Bounded deterministic report-validation failure codes."""

    SUPPLIER_MISMATCH = "SUPPLIER_MISMATCH"
    INVESTIGATION_MISMATCH = "INVESTIGATION_MISMATCH"
    THREAD_MISMATCH = "THREAD_MISMATCH"
    RISK_MISMATCH = "RISK_MISMATCH"
    UNKNOWN_EVIDENCE = "UNKNOWN_EVIDENCE"
    INVALID_REPORT = "INVALID_REPORT"


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


class ValidationCheck(StrictAgentModel):
    """One deterministic validation check outcome."""

    name: SafeIdentifier
    passed: bool
    failure_code: ValidationFailureCode | None = None

    @model_validator(mode="after")
    def require_failure_code_when_failed(self) -> ValidationCheck:
        if not self.passed and self.failure_code is None:
            raise ValueError("failed validation checks require a failure code")
        if self.passed and self.failure_code is not None:
            raise ValueError("passed validation checks must not include a failure code")
        return self


class InvestigationValidationResult(StrictAgentModel):
    """Deterministic validation result persisted with the investigation state."""

    passed: bool
    checks: tuple[ValidationCheck, ...]
    failure_codes: tuple[ValidationFailureCode, ...] = ()

    @model_validator(mode="after")
    def require_consistent_failure_codes(self) -> InvestigationValidationResult:
        expected = tuple(check.failure_code for check in self.checks if check.failure_code)
        if self.failure_codes != expected:
            raise ValueError("validation failure codes must match failed checks")
        if self.passed != (not expected):
            raise ValueError("validation pass flag must match failed checks")
        return self


class HumanReviewRecord(StrictAgentModel):
    """Persisted human review audit record."""

    review_id: UUID = Field(default_factory=uuid4)
    status: HumanReviewStatus
    reviewer_id: SafeIdentifier | None = None
    reviewed_at: datetime | None = None
    reason: ReviewComment | None = None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_reviewed_at(cls, value: datetime | None) -> datetime | None:
        if value is None:
            return None
        return require_aware_utc(value)

    @model_validator(mode="after")
    def require_final_review_metadata(self) -> HumanReviewRecord:
        if self.status in {
            HumanReviewStatus.APPROVED,
            HumanReviewStatus.REJECTED,
        } and (self.reviewer_id is None or self.reviewed_at is None):
            raise ValueError("final human reviews require reviewer_id and reviewed_at")
        if self.status is HumanReviewStatus.REJECTED and self.reason is None:
            raise ValueError("rejected human reviews require a reason")
        if self.status in {HumanReviewStatus.NOT_REQUESTED, HumanReviewStatus.PENDING} and (
            self.reviewer_id is not None or self.reviewed_at is not None or self.reason is not None
        ):
            raise ValueError("non-final human reviews must not include reviewer metadata")
        return self


class SubmitHumanReviewRequest(StrictAgentModel):
    """Public input for resuming a pending human-review interrupt."""

    investigation_id: UUID
    thread_id: UUID
    decision: HumanReviewDecision
    reviewer_id: SafeIdentifier
    reviewed_at: datetime
    reason: ReviewComment | None = None

    @field_validator("reviewed_at")
    @classmethod
    def require_aware_reviewed_at(cls, value: datetime) -> datetime:
        return require_aware_utc(value)

    @model_validator(mode="after")
    def require_rejection_reason(self) -> SubmitHumanReviewRequest:
        if self.decision is HumanReviewDecision.REJECT and self.reason is None:
            raise ValueError("rejected human reviews require a reason")
        return self

    def to_record(self) -> HumanReviewRecord:
        """Convert a validated submission into a final review record."""

        return HumanReviewRecord(
            status=(
                HumanReviewStatus.APPROVED
                if self.decision is HumanReviewDecision.APPROVE
                else HumanReviewStatus.REJECTED
            ),
            reviewer_id=self.reviewer_id,
            reviewed_at=self.reviewed_at,
            reason=self.reason,
        )


class HumanReviewInterruptPayload(StrictAgentModel):
    """Sanitized payload surfaced by the LangGraph interrupt."""

    investigation_id: UUID
    thread_id: UUID
    supplier_id: SupplierId
    risk_score: RiskScore
    risk_level: RiskLevel
    executive_summary: str
    recommendations: tuple[str, ...]
    evidence_keys: tuple[EvidenceKey, ...]
    validation_passed: bool


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
    supplier_profile: dict[str, object] | None = None
    current_risk: dict[str, object] | None = None
    risk_history: tuple[dict[str, object], ...] = ()
    evidence: tuple[dict[str, object], ...] = ()
    report: InvestigationReport | None = None
    error_code: str | None = None
    error_message: str | None = None
    provider_failure_category: ProviderFailureCategory | None = None
    provider_exception_class: str | None = None
    provider_status_code: str | None = None
    validation_result: InvestigationValidationResult | None = None
    human_review_status: HumanReviewStatus = HumanReviewStatus.NOT_REQUESTED
    human_review: HumanReviewRecord | None = None

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
    supplier_profile: NotRequired[dict[str, object] | None]
    current_risk: NotRequired[dict[str, object] | None]
    risk_history: NotRequired[list[dict[str, object]]]
    evidence: NotRequired[list[dict[str, object]]]
    report: NotRequired[dict[str, object] | None]
    error_code: NotRequired[str | None]
    error_message: NotRequired[str | None]
    provider_failure_category: NotRequired[str | None]
    provider_exception_class: NotRequired[str | None]
    provider_status_code: NotRequired[str | None]
    validation_result: NotRequired[dict[str, object] | None]
    human_review_status: NotRequired[str]
    human_review: NotRequired[dict[str, object] | None]


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
        "supplier_profile": snapshot.supplier_profile,
        "current_risk": snapshot.current_risk,
        "risk_history": list(snapshot.risk_history),
        "evidence": list(snapshot.evidence),
        "report": (None if snapshot.report is None else snapshot.report.model_dump(mode="json")),
        "error_code": snapshot.error_code,
        "error_message": snapshot.error_message,
        "provider_failure_category": (
            None
            if snapshot.provider_failure_category is None
            else snapshot.provider_failure_category.value
        ),
        "provider_exception_class": snapshot.provider_exception_class,
        "provider_status_code": snapshot.provider_status_code,
        "validation_result": (
            None
            if snapshot.validation_result is None
            else snapshot.validation_result.model_dump(mode="json")
        ),
        "human_review_status": snapshot.human_review_status.value,
        "human_review": (
            None if snapshot.human_review is None else snapshot.human_review.model_dump(mode="json")
        ),
    }


def snapshot_from_state(state: InvestigationState | dict[str, object]) -> InvestigationSnapshot:
    """Validate persisted LangGraph state at the public boundary."""

    evidence_keys = state["evidence_keys"]
    if not isinstance(evidence_keys, Iterable) or isinstance(evidence_keys, str):
        raise ValueError("evidence_keys must be an iterable of strings")
    report_value = state.get("report")
    validation_result_value = state.get("validation_result")
    human_review_value = state.get("human_review")
    return InvestigationSnapshot(
        investigation_id=UUID(str(state["investigation_id"])),
        thread_id=UUID(str(state["thread_id"])),
        supplier_id=str(state["supplier_id"]),
        question=str(state["question"]),
        status=InvestigationStatus(str(state["status"])),
        created_at=datetime_from_state(str(state["created_at"])),
        updated_at=datetime_from_state(str(state["updated_at"])),
        evidence_keys=tuple(str(key) for key in evidence_keys),
        supplier_profile=_optional_mapping(state.get("supplier_profile")),
        current_risk=_optional_mapping(state.get("current_risk")),
        risk_history=_mapping_tuple(state.get("risk_history", [])),
        evidence=_mapping_tuple(state.get("evidence", [])),
        report=(
            None
            if report_value is None
            else InvestigationReport.model_validate_json(json.dumps(report_value, sort_keys=True))
        ),
        error_code=(None if state.get("error_code") is None else str(state.get("error_code"))),
        error_message=(
            None if state.get("error_message") is None else str(state.get("error_message"))
        ),
        provider_failure_category=(
            None
            if state.get("provider_failure_category") is None
            else ProviderFailureCategory(str(state.get("provider_failure_category")))
        ),
        provider_exception_class=(
            None
            if state.get("provider_exception_class") is None
            else str(state.get("provider_exception_class"))
        ),
        provider_status_code=(
            None
            if state.get("provider_status_code") is None
            else str(state.get("provider_status_code"))
        ),
        validation_result=(
            None
            if validation_result_value is None
            else InvestigationValidationResult.model_validate_json(
                json.dumps(validation_result_value, sort_keys=True)
            )
        ),
        human_review_status=HumanReviewStatus(
            str(state.get("human_review_status", HumanReviewStatus.NOT_REQUESTED.value))
        ),
        human_review=(
            None
            if human_review_value is None
            else HumanReviewRecord.model_validate_json(
                json.dumps(human_review_value, sort_keys=True)
            )
        ),
    )


def _optional_mapping(value: object) -> dict[str, object] | None:
    if value is None:
        return None
    if not isinstance(value, dict):
        raise ValueError("state object field must be a mapping")
    return dict(value)


def _mapping_tuple(value: object) -> tuple[dict[str, object], ...]:
    if not isinstance(value, Iterable) or isinstance(value, (str, bytes)):
        raise ValueError("state list field must be an iterable of mappings")
    result: list[dict[str, object]] = []
    for item in value:
        if not isinstance(item, dict):
            raise ValueError("state list field must contain mappings")
        result.append(dict(item))
    return tuple(result)
