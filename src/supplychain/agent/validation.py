"""Deterministic investigation report validation."""

from __future__ import annotations

import time
from uuid import UUID

from supplychain.agent.models import (
    InvestigationValidationResult,
    ValidationCheck,
    ValidationFailureCode,
)
from supplychain.agent.reports import InvestigationReport
from supplychain.contracts import CanonicalEvent
from supplychain.observability import ObservabilityRuntime
from supplychain.observability.runtime import TelemetryOutcome, elapsed_ms
from supplychain.risk import SupplierRiskAssessment
from supplychain.risk.models import SupplierId


class InvestigationReportValidator:
    """Validate cross-object investigation report invariants without an LLM."""

    def __init__(self, observability: ObservabilityRuntime | None = None) -> None:
        self._observability = observability or ObservabilityRuntime.disabled()

    def validate(
        self,
        *,
        report: InvestigationReport,
        current_risk: SupplierRiskAssessment,
        evidence: tuple[CanonicalEvent, ...],
        supplier_id: SupplierId,
        investigation_id: UUID,
        thread_id: UUID,
        expected_thread_id: UUID | None = None,
    ) -> InvestigationValidationResult:
        """Return deterministic validation results for one generated report."""

        started_at = time.perf_counter()
        with self._observability.span(
            "supplychain.investigation.validate",
            attributes={
                "component": "validation",
                "operation": "validate_investigation_report",
                "supplier_id": supplier_id,
                "investigation_id": str(investigation_id),
                "thread_id": str(thread_id),
            },
        ) as span:
            allowed_evidence_keys = {event.metadata.deduplication_key for event in evidence}
            cited_evidence_keys = {
                evidence_key
                for finding in report.evidence_findings
                for evidence_key in finding.evidence_keys
            }
            risk_fields_match = _risk_fields_match(report, current_risk)
            sections_present = _has_required_generated_sections(report)
            checks = (
                ValidationCheck(
                    name="supplier_identity",
                    passed=report.supplier_id == supplier_id == current_risk.supplier_id,
                    failure_code=(
                        None
                        if report.supplier_id == supplier_id == current_risk.supplier_id
                        else ValidationFailureCode.SUPPLIER_MISMATCH
                    ),
                ),
                ValidationCheck(
                    name="investigation_identity",
                    passed=report.investigation_id == investigation_id,
                    failure_code=(
                        None
                        if report.investigation_id == investigation_id
                        else ValidationFailureCode.INVESTIGATION_MISMATCH
                    ),
                ),
                ValidationCheck(
                    name="thread_identity",
                    passed=expected_thread_id is None or thread_id == expected_thread_id,
                    failure_code=(
                        None
                        if expected_thread_id is None or thread_id == expected_thread_id
                        else ValidationFailureCode.THREAD_MISMATCH
                    ),
                ),
                ValidationCheck(
                    name="risk_immutability",
                    passed=risk_fields_match,
                    failure_code=(
                        None if risk_fields_match else ValidationFailureCode.RISK_MISMATCH
                    ),
                ),
                ValidationCheck(
                    name="evidence_integrity",
                    passed=cited_evidence_keys <= allowed_evidence_keys,
                    failure_code=(
                        None
                        if cited_evidence_keys <= allowed_evidence_keys
                        else ValidationFailureCode.UNKNOWN_EVIDENCE
                    ),
                ),
                ValidationCheck(
                    name="structural_validity",
                    passed=sections_present,
                    failure_code=(
                        None if sections_present else ValidationFailureCode.INVALID_REPORT
                    ),
                ),
            )
            failure_codes = tuple(check.failure_code for check in checks if check.failure_code)
            result = InvestigationValidationResult(
                passed=not failure_codes,
                checks=checks,
                failure_codes=failure_codes,
            )
            outcome = TelemetryOutcome.SUCCESS if result.passed else TelemetryOutcome.FAILURE
            self._observability.record_operation(
                component="validation",
                operation="validate_investigation_report",
                outcome=outcome,
                duration_ms=elapsed_ms(started_at),
                attributes={
                    "validation_outcome": "passed" if result.passed else "failed",
                    "validation_failure_code": (
                        result.failure_codes[0].value if result.failure_codes else None
                    ),
                },
            )
            self._observability.set_span_status(span, outcome)
            return result


def _risk_fields_match(
    report: InvestigationReport,
    current_risk: SupplierRiskAssessment,
) -> bool:
    return (
        report.risk_score == current_risk.risk_score
        and report.risk_level == current_risk.risk_level
        and report.risk_model_version == current_risk.model_version
        and report.structural_score == current_risk.structural_score
        and report.weather_score == current_risk.weather_score
        and report.seismic_score == current_risk.seismic_score
        and report.dominant_factor == current_risk.dominant_factor
        and report.factor_scores == current_risk.structural
    )


def _has_required_generated_sections(report: InvestigationReport) -> bool:
    return bool(
        report.executive_summary
        and report.key_drivers
        and report.uncertainties
        and report.recommendations
    )
