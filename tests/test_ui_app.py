from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID

from streamlit.testing.v1 import AppTest

from supplychain.agent.data import RiskEvidenceInput, RiskHistoryInput
from supplychain.agent.models import (
    HumanReviewDecision,
    HumanReviewRecord,
    HumanReviewStatus,
    InvestigationSnapshot,
    InvestigationStatus,
    InvestigationValidationResult,
    SubmitHumanReviewRequest,
    ValidationCheck,
)
from supplychain.agent.reports import EvidenceFinding, InvestigationReport
from supplychain.contracts import CanonicalEvent
from supplychain.domain import Criticality, SupplierCategory
from supplychain.risk import RiskFactorFamily, RiskLevel
from supplychain.risk.models import StructuralRiskBreakdown, SupplierRiskAssessment
from supplychain.ui.app import (
    ACTIVE_INVESTIGATION_STATE_KEY,
)
from supplychain.ui.data import PortfolioSnapshot, PortfolioSupplierRiskRow, portfolio_summary

NOW = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)

INVESTIGATION_ID = UUID("11111111-1111-4111-8111-111111111111")
THREAD_ID = UUID("22222222-2222-4222-8222-222222222222")


class FakePortfolioService:
    def __init__(self, snapshot: PortfolioSnapshot) -> None:
        self.snapshot = snapshot
        self.calls = 0

    def get_current_portfolio(self, *, limit: int) -> PortfolioSnapshot:
        self.calls += 1
        return self.snapshot


class FakeInvestigationService:
    def __init__(self, result: InvestigationSnapshot) -> None:
        self.result = result
        self.run_calls = 0
        self.review_requests: list[SubmitHumanReviewRequest] = []

    def run_investigation(self, request: object) -> InvestigationSnapshot:
        self.run_calls += 1
        return self.result

    def submit_review(self, request: SubmitHumanReviewRequest) -> InvestigationSnapshot:
        self.review_requests.append(request)
        review = request.to_record()
        reviewed = self.result.model_copy(
            update={
                "human_review_status": review.status,
                "human_review": review,
            }
        )
        self.result = reviewed
        return reviewed

    def get_investigation_state(self, thread_id: str) -> InvestigationSnapshot:
        return self.result


class EmptyAgentDataService:
    def get_supplier_risk_history(
        self,
        request: RiskHistoryInput,
    ) -> tuple[SupplierRiskAssessment, ...]:
        return ()

    def get_risk_evidence(self, request: RiskEvidenceInput) -> tuple[CanonicalEvent, ...]:
        return ()


def test_streamlit_application_starts_with_safe_unavailable_state() -> None:
    app_path = Path.cwd() / "src" / "supplychain" / "ui" / "app.py"
    app = AppTest.from_file(app_path).run(timeout=10)

    assert not app.exception
    assert any("SupplyChain Sentinel" in item.value for item in app.title)


def test_risk_portfolio_page_renders_kpis_and_table_with_fake_service() -> None:
    service = FakePortfolioService(portfolio_snapshot())
    app = AppTest.from_function(risk_portfolio_script, args=(service,)).run()

    assert service.calls == 1
    assert not app.exception
    assert any("Risk Portfolio" in item.value for item in app.header)
    assert len(app.metric) >= 4
    assert len(app.dataframe) == 1


def test_supplier_explorer_renders_profile_current_risk_and_empty_evidence() -> None:
    service = FakePortfolioService(portfolio_snapshot())
    app = AppTest.from_function(
        supplier_explorer_script,
        args=(service, EmptyAgentDataService()),
    ).run()

    assert not app.exception
    assert any("Supplier Explorer" in item.value for item in app.header)
    assert any("No qualifying environmental evidence" in item.value for item in app.info)


def test_ai_page_render_does_not_execute_investigation_until_button_click() -> None:
    portfolio = FakePortfolioService(portfolio_snapshot())
    investigation = FakeInvestigationService(pending_snapshot())
    app = AppTest.from_function(ai_investigation_script, args=(portfolio, investigation)).run()

    assert not app.exception
    assert investigation.run_calls == 0

    app.button[0].click().run()

    assert investigation.run_calls == 1
    assert app.session_state[ACTIVE_INVESTIGATION_STATE_KEY].thread_id == THREAD_ID

    app.run()

    assert investigation.run_calls == 1


def test_ai_failed_investigation_renders_sanitized_failure() -> None:
    portfolio = FakePortfolioService(portfolio_snapshot())
    investigation = FakeInvestigationService(failed_snapshot())
    app = AppTest.from_function(ai_investigation_script, args=(portfolio, investigation)).run()

    app.button[0].click().run()

    assert not app.exception
    assert any("Investigation analysis failed" in item.value for item in app.error)
    assert not any("PROVIDER_BODY_SENTINEL" in item.value for item in app.markdown)


def test_pending_review_approve_submits_once_and_duplicate_rerun_is_safe() -> None:
    portfolio = FakePortfolioService(portfolio_snapshot())
    investigation = FakeInvestigationService(pending_snapshot())

    app = AppTest.from_function(
        ai_investigation_with_active_script,
        args=(portfolio, investigation, pending_snapshot()),
    ).run()
    app.text_input[0].set_value("reviewer-001")
    app.radio[0].set_value("APPROVE")
    app.button[-1].click().run()

    assert not app.exception
    assert len(investigation.review_requests) == 1
    assert investigation.review_requests[0].decision is HumanReviewDecision.APPROVE

    app.run()

    assert len(investigation.review_requests) == 1


def test_pending_review_reject_requires_reason_then_submits() -> None:
    portfolio = FakePortfolioService(portfolio_snapshot())
    investigation = FakeInvestigationService(pending_snapshot())

    app = AppTest.from_function(
        ai_investigation_with_active_script,
        args=(portfolio, investigation, pending_snapshot()),
    ).run()
    app.text_input[0].set_value("reviewer-001")
    app.radio[0].set_value("REJECT")
    app.button[-1].click().run()

    assert len(investigation.review_requests) == 0
    assert any("rejection reason is required" in item.value for item in app.error)

    app.text_area[-1].set_value("Needs operations review.")
    app.button[-1].click().run()

    assert len(investigation.review_requests) == 1
    assert investigation.review_requests[0].decision is HumanReviewDecision.REJECT
    assert investigation.review_requests[0].reason == "Needs operations review."


def portfolio_snapshot() -> PortfolioSnapshot:
    rows = (portfolio_row(supplier_id="SUP-000001", risk_score=41.83, risk_level=RiskLevel.MEDIUM),)
    return PortfolioSnapshot(rows=rows, summary=portfolio_summary(rows), executions=())


def risk_portfolio_script(service: object) -> None:
    from typing import cast

    from supplychain.ui.app import PortfolioDataServiceLike, render_risk_portfolio_page

    render_risk_portfolio_page(cast(PortfolioDataServiceLike, service))


def supplier_explorer_script(
    service: object,
    agent_data_service: object,
) -> None:
    from typing import cast

    from supplychain.ui.app import (
        AgentDataServiceLike,
        PortfolioDataServiceLike,
        render_supplier_explorer_page,
    )

    render_supplier_explorer_page(
        cast(PortfolioDataServiceLike, service),
        cast(AgentDataServiceLike, agent_data_service),
    )


def ai_investigation_script(
    portfolio_service: object,
    investigation_service: object,
) -> None:
    from typing import cast

    from supplychain.ui.app import (
        InvestigationServiceLike,
        PortfolioDataServiceLike,
        render_ai_investigation_page,
    )

    render_ai_investigation_page(
        cast(PortfolioDataServiceLike, portfolio_service),
        cast(InvestigationServiceLike, investigation_service),
    )


def ai_investigation_with_active_script(
    portfolio_service: object,
    investigation_service: object,
    active_snapshot: object,
) -> None:
    from typing import cast

    import streamlit as st

    from supplychain.agent.models import InvestigationSnapshot
    from supplychain.ui.app import (
        ACTIVE_INVESTIGATION_STATE_KEY,
        InvestigationServiceLike,
        PortfolioDataServiceLike,
        render_ai_investigation_page,
    )

    if ACTIVE_INVESTIGATION_STATE_KEY not in st.session_state:
        st.session_state[ACTIVE_INVESTIGATION_STATE_KEY] = cast(
            InvestigationSnapshot,
            active_snapshot,
        )
    render_ai_investigation_page(
        cast(PortfolioDataServiceLike, portfolio_service),
        cast(InvestigationServiceLike, investigation_service),
    )


def portfolio_row(
    *,
    supplier_id: str,
    risk_score: float,
    risk_level: RiskLevel,
) -> PortfolioSupplierRiskRow:
    return PortfolioSupplierRiskRow(
        supplier_id=supplier_id,
        supplier_name="Synthetic Components North",
        category=SupplierCategory.ELECTRONIC_COMPONENTS,
        criticality=Criticality.HIGH,
        country_code="US",
        region="WA",
        city="Seattle",
        annual_spend_usd=1_250_000,
        typical_lead_time_days=28,
        dependency_score=0.74,
        single_source=True,
        assessed_at=NOW,
        risk_score=risk_score,
        risk_level=risk_level,
        model_version="1.0.0",
        structural_score=83.66,
        weather_score=0.0,
        seismic_score=0.0,
        dominant_factor=RiskFactorFamily.STRUCTURAL,
        criticality_component=0.75,
        dependency_component=0.74,
        single_source_component=1.0,
        lead_time_component=0.08,
        relevant_weather_event_count=0,
        relevant_seismic_event_count=0,
        evidence_deduplication_keys=(),
    )


def pending_snapshot() -> InvestigationSnapshot:
    report = InvestigationReport(
        investigation_id=INVESTIGATION_ID,
        supplier_id="SUP-000001",
        generated_at=NOW,
        risk_score=41.83,
        risk_level=RiskLevel.MEDIUM,
        risk_model_version="1.0.0",
        structural_score=83.66,
        weather_score=0.0,
        seismic_score=0.0,
        dominant_factor=RiskFactorFamily.STRUCTURAL,
        factor_scores=StructuralRiskBreakdown(
            criticality_component=0.75,
            dependency_component=0.74,
            single_source_component=1.0,
            lead_time_component=0.08,
        ),
        executive_summary="Current risk is mainly structural.",
        key_drivers=("Single-source exposure drives risk.",),
        evidence_findings=(EvidenceFinding(finding="No evidence cited.", evidence_keys=()),),
        uncertainties=("Environmental evidence is absent.",),
        recommendations=("Monitor alternate sourcing.",),
        evidence_deduplication_keys_used=(),
    )
    return InvestigationSnapshot(
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
        supplier_id="SUP-000001",
        question="What should operations monitor?",
        status=InvestigationStatus.COMPLETED,
        created_at=NOW,
        updated_at=NOW,
        report=report,
        validation_result=InvestigationValidationResult(
            passed=True,
            checks=(ValidationCheck(name="risk_immutability", passed=True),),
            failure_codes=(),
        ),
        human_review_status=HumanReviewStatus.PENDING,
        human_review=HumanReviewRecord(status=HumanReviewStatus.PENDING),
    )


def failed_snapshot() -> InvestigationSnapshot:
    return InvestigationSnapshot(
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
        supplier_id="SUP-000001",
        question="What should operations monitor?",
        status=InvestigationStatus.FAILED,
        created_at=NOW,
        updated_at=NOW,
        error_message="Investigation analysis failed",
        provider_status_code="404",
    )
