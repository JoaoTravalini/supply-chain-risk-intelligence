"""Structured investigation report contracts."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

from supplychain.risk.models import (
    EvidenceKey,
    RiskFactorFamily,
    RiskLevel,
    RiskScore,
    SemanticVersion,
    StructuralRiskBreakdown,
    SupplierId,
)

GeneratedText = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]


class StrictReportModel(BaseModel):
    """Base for immutable, strict investigation report models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EvidenceFinding(StrictReportModel):
    """One generated finding with allowlisted canonical evidence references."""

    finding: GeneratedText
    evidence_keys: tuple[EvidenceKey, ...] = ()


class InvestigationAnalysis(StrictReportModel):
    """Model-generated analysis fields only."""

    executive_summary: GeneratedText
    key_drivers: tuple[GeneratedText, ...] = Field(min_length=1, max_length=6)
    evidence_findings: tuple[EvidenceFinding, ...] = Field(max_length=8)
    uncertainties: tuple[GeneratedText, ...] = Field(min_length=1, max_length=6)
    recommendations: tuple[GeneratedText, ...] = Field(min_length=1, max_length=6)


class InvestigationReport(StrictReportModel):
    """Final application-owned structured supplier risk investigation report."""

    investigation_id: UUID
    supplier_id: SupplierId
    generated_at: datetime
    risk_score: RiskScore
    risk_level: RiskLevel
    risk_model_version: SemanticVersion
    structural_score: RiskScore
    weather_score: RiskScore
    seismic_score: RiskScore
    dominant_factor: RiskFactorFamily
    factor_scores: StructuralRiskBreakdown
    executive_summary: GeneratedText
    key_drivers: tuple[GeneratedText, ...]
    evidence_findings: tuple[EvidenceFinding, ...]
    uncertainties: tuple[GeneratedText, ...]
    recommendations: tuple[GeneratedText, ...]
    evidence_deduplication_keys_used: tuple[EvidenceKey, ...]

    @field_validator("generated_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("generated_at must be timezone-aware")
        return value.astimezone(UTC)


def validate_analysis_evidence_references(
    analysis: InvestigationAnalysis,
    *,
    allowed_evidence_keys: set[str],
) -> InvestigationAnalysis:
    """Reject model-generated evidence references outside the retrieved set."""

    cited_keys = {
        evidence_key
        for finding in analysis.evidence_findings
        for evidence_key in finding.evidence_keys
    }
    unknown_keys = cited_keys - allowed_evidence_keys
    if unknown_keys:
        raise ValueError("model cited evidence that was not retrieved")
    return analysis
