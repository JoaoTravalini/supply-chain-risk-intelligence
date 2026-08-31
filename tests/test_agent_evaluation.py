from __future__ import annotations

import supplychain.agent as agent
from supplychain.agent.evaluation import run_evaluation_suite
from supplychain.agent.evaluation.harness import format_evaluation_summary


def test_stage_16_agent_evaluation_suite_passes_all_contract_cases() -> None:
    result = run_evaluation_suite()

    assert result.passed is True
    assert result.metrics.total_cases == 6
    assert result.metrics.passed_cases == 6
    assert result.metrics.failed_cases == 0
    assert result.metrics.pass_rate == 1.0
    assert result.metrics.risk_immutability_pass_rate == 1.0
    assert result.metrics.evidence_integrity_pass_rate == 1.0
    assert result.metrics.hitl_routing_pass_rate == 1.0
    assert result.metrics.security_boundary_pass_rate == 1.0
    assert {case.case_id for case in result.cases} == {"A", "B", "C", "D", "E", "F"}


def test_stage_16_evaluation_summary_is_concise_and_sanitized() -> None:
    summary = format_evaluation_summary(run_evaluation_suite())

    assert "total=6 passed=6 failed=0 pass_rate=100.00%" in summary
    assert "GEMINI_API_KEY" not in summary
    assert "postgresql://" not in summary
    assert "SELECT " not in summary


def test_stage_16_public_agent_api_exports_review_and_validation_contracts() -> None:
    assert agent.HumanReviewStatus.PENDING.value == "PENDING"
    assert agent.HumanReviewDecision.APPROVE.value == "APPROVE"
    assert agent.ValidationFailureCode.RISK_MISMATCH.value == "RISK_MISMATCH"
    assert agent.InvestigationReportValidator is not None
