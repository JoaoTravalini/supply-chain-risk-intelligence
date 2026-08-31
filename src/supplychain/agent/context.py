"""Bounded trusted-context construction for supplier risk investigations."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, cast

from pydantic import BaseModel, ConfigDict, JsonValue, StringConstraints

from supplychain.agent.errors import InvestigationContextError
from supplychain.contracts import CanonicalEvent
from supplychain.domain import Supplier
from supplychain.risk import SupplierRiskAssessment
from supplychain.risk.models import EvidenceKey, RiskLevel, RiskScore, SupplierId

DEFAULT_MAX_QUESTION_LENGTH = 2_000
DEFAULT_MAX_EVIDENCE_EVENTS = 20
DEFAULT_MAX_TEXT_FIELD_LENGTH = 500
DEFAULT_MAX_EVIDENCE_PAYLOAD_BYTES = 2_000
DEFAULT_MAX_SERIALIZED_CONTEXT_BYTES = 20_000

BoundedText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=2_000, strict=True),
]
ShortText = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=500, strict=True),
]


class StrictContextModel(BaseModel):
    """Base for immutable, strict investigation context models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SupplierContext(StrictContextModel):
    """Reduced Supplier context sent to the model."""

    supplier_id: SupplierId
    name: ShortText
    category: ShortText
    criticality: ShortText
    country_code: ShortText
    region: ShortText
    city: ShortText
    annual_spend_usd: int
    typical_lead_time_days: int
    dependency_score: float
    single_source: bool


class RiskContext(StrictContextModel):
    """Authoritative current-risk context sent to the model."""

    assessed_at: datetime
    risk_score: RiskScore
    risk_level: RiskLevel
    risk_model_version: ShortText
    structural_score: RiskScore
    weather_score: RiskScore
    seismic_score: RiskScore
    structural_factors: dict[str, float]
    relevant_weather_event_count: int
    relevant_seismic_event_count: int
    dominant_factor: ShortText
    evidence_deduplication_keys: tuple[EvidenceKey, ...]


class RiskHistoryContext(StrictContextModel):
    """Bounded historical risk row sent to the model."""

    assessed_at: datetime
    risk_score: RiskScore
    risk_level: RiskLevel
    dominant_factor: ShortText


class EvidenceContext(StrictContextModel):
    """Reduced canonical evidence context sent to the model."""

    evidence_key: EvidenceKey
    event_type: ShortText
    event_time: datetime
    source_provider: ShortText
    source_event_id: ShortText
    country_code: ShortText | None = None
    region: ShortText | None = None
    payload: dict[str, JsonValue]


class InvestigationContext(StrictContextModel):
    """Bounded, structured model input for one supplier investigation."""

    prompt_version: ShortText
    question: BoundedText
    supplier: SupplierContext
    current_risk: RiskContext
    risk_history: tuple[RiskHistoryContext, ...]
    evidence: tuple[EvidenceContext, ...]
    zero_evidence: bool


@dataclass(frozen=True, slots=True)
class InvestigationContextLimits:
    """Size limits for model-facing investigation context."""

    max_question_length: int = DEFAULT_MAX_QUESTION_LENGTH
    max_evidence_events: int = DEFAULT_MAX_EVIDENCE_EVENTS
    max_text_field_length: int = DEFAULT_MAX_TEXT_FIELD_LENGTH
    max_evidence_payload_bytes: int = DEFAULT_MAX_EVIDENCE_PAYLOAD_BYTES
    max_serialized_context_bytes: int = DEFAULT_MAX_SERIALIZED_CONTEXT_BYTES

    def __post_init__(self) -> None:
        for name in (
            "max_question_length",
            "max_evidence_events",
            "max_text_field_length",
            "max_evidence_payload_bytes",
            "max_serialized_context_bytes",
        ):
            if getattr(self, name) <= 0:
                raise InvestigationContextError(f"{name} must be positive")


DEFAULT_CONTEXT_LIMITS = InvestigationContextLimits()


def build_investigation_context(
    *,
    question: str,
    supplier: Supplier,
    current_risk: SupplierRiskAssessment,
    risk_history: tuple[SupplierRiskAssessment, ...],
    evidence: tuple[CanonicalEvent, ...],
    prompt_version: str,
    limits: InvestigationContextLimits | None = None,
) -> InvestigationContext:
    """Build bounded structured context for Gemini."""

    limits = DEFAULT_CONTEXT_LIMITS if limits is None else limits
    normalized_question = question.strip()
    if not normalized_question:
        raise InvestigationContextError("Investigation question must not be blank")
    if len(normalized_question) > limits.max_question_length:
        raise InvestigationContextError("Investigation question exceeds maximum length")
    if len(evidence) > limits.max_evidence_events:
        raise InvestigationContextError("Investigation evidence exceeds maximum count")

    context = InvestigationContext(
        prompt_version=prompt_version,
        question=normalized_question,
        supplier=_supplier_context(supplier, limits),
        current_risk=_risk_context(current_risk, limits),
        risk_history=tuple(_history_context(item, limits) for item in risk_history),
        evidence=tuple(_evidence_context(item, limits) for item in evidence),
        zero_evidence=not evidence,
    )
    _enforce_total_size(context, limits)
    return context


def _supplier_context(supplier: Supplier, limits: InvestigationContextLimits) -> SupplierContext:
    return SupplierContext(
        supplier_id=supplier.supplier_id,
        name=_bounded_text(supplier.name, limits),
        category=_bounded_text(supplier.category.value, limits),
        criticality=_bounded_text(supplier.criticality.value, limits),
        country_code=supplier.location.country_code,
        region=_bounded_text(supplier.location.region, limits),
        city=_bounded_text(supplier.location.city, limits),
        annual_spend_usd=supplier.annual_spend_usd,
        typical_lead_time_days=supplier.typical_lead_time_days,
        dependency_score=supplier.dependency_score,
        single_source=supplier.single_source,
    )


def _risk_context(
    risk: SupplierRiskAssessment,
    limits: InvestigationContextLimits,
) -> RiskContext:
    return RiskContext(
        assessed_at=risk.assessed_at,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level,
        risk_model_version=_bounded_text(risk.model_version, limits),
        structural_score=risk.structural_score,
        weather_score=risk.weather_score,
        seismic_score=risk.seismic_score,
        structural_factors=risk.structural.model_dump(),
        relevant_weather_event_count=risk.relevant_weather_event_count,
        relevant_seismic_event_count=risk.relevant_seismic_event_count,
        dominant_factor=_bounded_text(risk.dominant_factor.value, limits),
        evidence_deduplication_keys=risk.evidence_deduplication_keys,
    )


def _history_context(
    risk: SupplierRiskAssessment,
    limits: InvestigationContextLimits,
) -> RiskHistoryContext:
    return RiskHistoryContext(
        assessed_at=risk.assessed_at,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level,
        dominant_factor=_bounded_text(risk.dominant_factor.value, limits),
    )


def _evidence_context(event: CanonicalEvent, limits: InvestigationContextLimits) -> EvidenceContext:
    return EvidenceContext(
        evidence_key=event.metadata.deduplication_key,
        event_type=_bounded_text(event.event_type.value, limits),
        event_time=event.event_time,
        source_provider=_bounded_text(event.source.provider, limits),
        source_event_id=_bounded_text(event.source.source_event_id, limits),
        country_code=None if event.location is None else event.location.country_code,
        region=None if event.location is None else _bounded_text(event.location.region, limits),
        payload=_bounded_payload(event.payload, limits),
    )


def _bounded_text(value: str | None, limits: InvestigationContextLimits) -> str:
    if value is None:
        return "not provided"
    stripped = value.strip()
    if not stripped:
        return "not provided"
    return stripped[: limits.max_text_field_length]


def _bounded_payload(
    payload: dict[str, JsonValue],
    limits: InvestigationContextLimits,
) -> dict[str, JsonValue]:
    serialized = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    if len(serialized.encode("utf-8")) <= limits.max_evidence_payload_bytes:
        return payload
    truncated = serialized.encode("utf-8")[: limits.max_evidence_payload_bytes].decode(
        "utf-8",
        errors="ignore",
    )
    return {"truncated_payload_json": cast(JsonValue, truncated)}


def _enforce_total_size(
    context: InvestigationContext,
    limits: InvestigationContextLimits,
) -> None:
    serialized = json.dumps(context.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
    if len(serialized.encode("utf-8")) > limits.max_serialized_context_bytes:
        raise InvestigationContextError("Investigation context exceeds maximum serialized size")
