"""Professional Streamlit application for SupplyChain Sentinel."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Protocol, cast

import streamlit as st
from pydantic import ValidationError

from supplychain.agent.data import AgentDataError, RiskEvidenceInput, RiskHistoryInput
from supplychain.agent.errors import AgentConfigurationError, AgentError, AgentPersistenceError
from supplychain.agent.models import (
    CreateInvestigationRequest,
    HumanReviewDecision,
    HumanReviewStatus,
    InvestigationSnapshot,
    InvestigationStatus,
    SubmitHumanReviewRequest,
)
from supplychain.agent.reports import InvestigationReport
from supplychain.contracts import CanonicalEvent
from supplychain.risk import RiskLevel, SupplierRiskAssessment
from supplychain.ui.data import (
    DEFAULT_PORTFOLIO_LIMIT,
    PortfolioSnapshot,
    PortfolioSupplierRiskRow,
    filter_portfolio_rows,
)
from supplychain.ui.presentation import (
    format_score,
    format_timestamp,
    highest_risk_rows,
    investigation_label,
    portfolio_table_rows,
    risk_level_distribution,
    safe_error_message,
)
from supplychain.ui.resources import (
    agent_data_service_resource,
    investigation_service_resource,
    portfolio_service_resource,
)

DEFAULT_INVESTIGATION_QUESTION = (
    "What are the main current risk drivers for this supplier, what evidence supports them, "
    "and what should an operations team monitor?"
)
PORTFOLIO_STATE_KEY = "supplychain_portfolio_snapshot"
SELECTED_SUPPLIER_STATE_KEY = "supplychain_selected_supplier_id"
ACTIVE_INVESTIGATION_STATE_KEY = "supplychain_active_investigation"


class AgentDataServiceLike(Protocol):
    """Subset of agent data reads used by Supplier Explorer."""

    def get_supplier_risk_history(
        self,
        request: RiskHistoryInput,
    ) -> tuple[SupplierRiskAssessment, ...]:
        """Return bounded supplier risk history."""

    def get_risk_evidence(self, request: RiskEvidenceInput) -> tuple[CanonicalEvent, ...]:
        """Return bounded canonical evidence."""


class PortfolioDataServiceLike(Protocol):
    """Subset of portfolio data reads used by the UI."""

    def get_current_portfolio(self, *, limit: int) -> PortfolioSnapshot:
        """Return a bounded current portfolio snapshot."""


class InvestigationServiceLike(Protocol):
    """Subset of InvestigationService used by the UI."""

    def run_investigation(self, request: CreateInvestigationRequest) -> InvestigationSnapshot:
        """Run one explicit investigation."""

    def submit_review(self, request: SubmitHumanReviewRequest) -> InvestigationSnapshot:
        """Submit a HITL review decision."""

    def get_investigation_state(self, thread_id: str) -> InvestigationSnapshot:
        """Retrieve one investigation state."""


def main() -> None:
    """Run the Streamlit application."""

    st.set_page_config(
        page_title="SupplyChain Sentinel",
        page_icon=None,
        layout="wide",
    )
    st.title("SupplyChain Sentinel")
    st.caption("Supply-chain risk intelligence with deterministic risk and reviewed AI analysis.")

    pages = [
        st.Page(render_risk_portfolio_page, title="Risk Portfolio"),
        st.Page(render_supplier_explorer_page, title="Supplier Explorer"),
        st.Page(render_ai_investigation_page, title="AI Investigation"),
    ]
    st.navigation(pages).run()


def render_risk_portfolio_page(
    portfolio_service: PortfolioDataServiceLike | None = None,
) -> None:
    """Render the portfolio overview."""

    st.header("Risk Portfolio")
    snapshot = _portfolio_snapshot(portfolio_service)
    if snapshot is None:
        return
    rows = snapshot.rows
    if not rows:
        st.info("No current Supplier risk rows are available.")
        return

    summary = snapshot.summary
    metric_cols = st.columns(4)
    metric_cols[0].metric("Suppliers", summary.total_suppliers)
    metric_cols[1].metric("Average risk", format_score(summary.average_risk_score))
    metric_cols[2].metric("Highest risk", format_score(summary.highest_risk_score))
    metric_cols[3].metric("Rows loaded", len(rows))

    with st.expander("Filters", expanded=True):
        filter_cols = st.columns(3)
        selected_levels = filter_cols[0].multiselect(
            "Risk level",
            options=[level.value for level in RiskLevel],
        )
        selected_categories = filter_cols[1].multiselect(
            "Category",
            options=sorted({row.category.value for row in rows}),
        )
        selected_countries = filter_cols[2].multiselect(
            "Country",
            options=sorted({row.country_code for row in rows}),
        )
    filtered = filter_portfolio_rows(
        rows,
        risk_levels={RiskLevel(level) for level in selected_levels},
        categories={row.category for row in rows if row.category.value in selected_categories},
        countries=set(selected_countries),
    )

    chart_cols = st.columns(2)
    chart_cols[0].subheader("Risk-Level Distribution")
    chart_cols[0].bar_chart(risk_level_distribution(filtered))
    chart_cols[1].subheader("Highest-Risk Suppliers")
    chart_cols[1].bar_chart(highest_risk_rows(filtered), x="Supplier", y="Risk Score")

    st.subheader("Current Supplier Risk")
    st.dataframe(portfolio_table_rows(filtered), use_container_width=True, hide_index=True)
    if st.button("Refresh portfolio"):
        st.session_state.pop(PORTFOLIO_STATE_KEY, None)
        st.rerun()


def render_supplier_explorer_page(
    portfolio_service: PortfolioDataServiceLike | None = None,
    agent_data_service: AgentDataServiceLike | None = None,
) -> None:
    """Render the Supplier Explorer page."""

    st.header("Supplier Explorer")
    snapshot = _portfolio_snapshot(portfolio_service)
    if snapshot is None:
        return
    if not snapshot.rows:
        st.info("No Suppliers are available for inspection.")
        return

    supplier = _supplier_selector(snapshot.rows)
    st.subheader("Supplier Profile")
    profile_cols = st.columns(4)
    profile_cols[0].metric("Supplier", supplier.supplier_name)
    profile_cols[1].metric("Country", supplier.country_code)
    profile_cols[2].metric("Criticality", supplier.criticality.value)
    profile_cols[3].metric("Single source", "Yes" if supplier.single_source else "No")
    st.table(
        {
            "Field": ["Category", "Region", "City", "Lead time", "Dependency", "Annual spend"],
            "Value": [
                supplier.category.value,
                supplier.region,
                supplier.city,
                f"{supplier.typical_lead_time_days} days",
                f"{supplier.dependency_score:.2f}",
                f"${supplier.annual_spend_usd:,.0f}",
            ],
        }
    )

    st.subheader("Current Risk")
    risk_cols = st.columns(4)
    risk_cols[0].metric("Risk score", format_score(supplier.risk_score))
    risk_cols[1].metric("Risk level", supplier.risk_level.value)
    risk_cols[2].metric("Model version", supplier.model_version)
    risk_cols[3].metric("Assessed at", format_timestamp(supplier.assessed_at))

    st.subheader("Factor Decomposition")
    st.caption("Deterministic Supplier Risk Model outputs")
    st.bar_chart(
        {
            "Structural": supplier.structural_score,
            "Weather": supplier.weather_score,
            "Seismic": supplier.seismic_score,
        }
    )

    service = _agent_data_service(agent_data_service)
    if service is None:
        st.info("Supplier history and evidence are unavailable until BigQuery is configured.")
        return
    _render_history_and_evidence(service, supplier)


def render_ai_investigation_page(
    portfolio_service: PortfolioDataServiceLike | None = None,
    investigation_service: InvestigationServiceLike | None = None,
) -> None:
    """Render the AI investigation and HITL page."""

    st.header("AI Investigation")
    st.info(
        "Investigations run only after the explicit button is pressed. "
        "The known external Gemini provider blocker is shown safely if it occurs."
    )
    snapshot = _portfolio_snapshot(portfolio_service)
    if snapshot is None:
        return
    if not snapshot.rows:
        st.info("No Suppliers are available for investigation.")
        return

    supplier = _supplier_selector(snapshot.rows)
    question = st.text_area(
        "Investigation question",
        value=DEFAULT_INVESTIGATION_QUESTION,
        max_chars=2_000,
    )
    if st.button("Run investigation", type="primary"):
        service = _investigation_service(investigation_service)
        if service is None:
            st.error("Investigation workflow is unavailable until configuration is complete.")
        else:
            with st.spinner("Running investigation"):
                try:
                    result = service.run_investigation(
                        CreateInvestigationRequest(
                            supplier_id=supplier.supplier_id,
                            question=question,
                            created_at=datetime.now(UTC),
                        )
                    )
                    st.session_state[ACTIVE_INVESTIGATION_STATE_KEY] = result
                except (AgentError, AgentDataError, ValidationError) as exc:
                    st.error(safe_error_message(exc))

    active = _active_investigation()
    if active is None:
        st.info("No active investigation has been run in this session.")
        return
    _render_investigation(active)
    if active.human_review_status is HumanReviewStatus.PENDING:
        _render_review_form(active, investigation_service)


def _portfolio_snapshot(
    service: PortfolioDataServiceLike | None,
) -> PortfolioSnapshot | None:
    cached = st.session_state.get(PORTFOLIO_STATE_KEY)
    if isinstance(cached, PortfolioSnapshot):
        return cached
    resolved_service = service or _session_portfolio_service() or _safe_portfolio_service()
    if resolved_service is None:
        st.warning("Portfolio data is unavailable until BigQuery configuration is complete.")
        return None
    with st.spinner("Loading portfolio"):
        try:
            snapshot = resolved_service.get_current_portfolio(limit=DEFAULT_PORTFOLIO_LIMIT)
        except Exception as exc:
            st.warning(safe_error_message(exc))
            return None
    st.session_state[PORTFOLIO_STATE_KEY] = snapshot
    return snapshot


def _supplier_selector(rows: tuple[PortfolioSupplierRiskRow, ...]) -> PortfolioSupplierRiskRow:
    supplier_ids = [row.supplier_id for row in rows]
    selected = st.selectbox(
        "Supplier",
        options=supplier_ids,
        index=_selected_supplier_index(supplier_ids),
        format_func=lambda supplier_id: _supplier_label(rows, str(supplier_id)),
    )
    st.session_state[SELECTED_SUPPLIER_STATE_KEY] = selected
    return next(row for row in rows if row.supplier_id == selected)


def _render_history_and_evidence(
    service: AgentDataServiceLike,
    supplier: PortfolioSupplierRiskRow,
) -> None:
    st.subheader("History")
    try:
        history = service.get_supplier_risk_history(
            RiskHistoryInput(supplier_id=supplier.supplier_id, limit=20)
        )
    except Exception as exc:
        st.warning(safe_error_message(exc))
        history = ()
    if history:
        st.dataframe(
            [
                {
                    "Assessed At": format_timestamp(item.assessed_at),
                    "Risk Score": item.risk_score,
                    "Risk Level": item.risk_level.value,
                }
                for item in history
            ],
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No bounded risk history is available for this Supplier.")

    st.subheader("Evidence")
    if not supplier.evidence_deduplication_keys:
        st.info("No qualifying environmental evidence is attached to the current risk assessment.")
        return
    try:
        evidence = service.get_risk_evidence(
            RiskEvidenceInput(evidence_deduplication_keys=supplier.evidence_deduplication_keys)
        )
    except Exception as exc:
        st.warning(safe_error_message(exc))
        return
    st.dataframe(
        [
            {
                "Evidence Key": event.metadata.deduplication_key,
                "Event Type": event.event_type.value,
                "Event Time": format_timestamp(event.event_time),
                "Provider": event.source.provider,
            }
            for event in evidence
        ],
        use_container_width=True,
        hide_index=True,
    )


def _render_investigation(snapshot: InvestigationSnapshot) -> None:
    st.subheader("Investigation State")
    st.write(investigation_label(snapshot))
    if snapshot.status is InvestigationStatus.FAILED:
        st.error(snapshot.error_message or "Investigation failed.")
        if snapshot.provider_failure_category is not None:
            st.write(f"Provider category: {snapshot.provider_failure_category.value}")
        if snapshot.provider_status_code is not None:
            st.write(f"Provider status/code: {snapshot.provider_status_code}")
        return
    if snapshot.report is None:
        st.info("Investigation report is not available yet.")
        return
    report = snapshot.report
    st.markdown("**Authoritative Data**")
    cols = st.columns(4)
    cols[0].metric("Supplier", report.supplier_id)
    cols[1].metric("Risk score", format_score(report.risk_score))
    cols[2].metric("Risk level", report.risk_level.value)
    cols[3].metric("Model version", report.risk_model_version)
    st.markdown("**AI-Generated Analysis**")
    st.write(report.executive_summary)
    _write_list("Key drivers", report.key_drivers)
    _write_findings(report)
    _write_list("Uncertainties", report.uncertainties)
    _write_list("Recommendations", report.recommendations)
    if snapshot.validation_result is not None:
        st.write(f"Validation passed: {snapshot.validation_result.passed}")
    if snapshot.human_review is not None and snapshot.human_review_status in {
        HumanReviewStatus.APPROVED,
        HumanReviewStatus.REJECTED,
    }:
        st.markdown("**Human Review**")
        st.write(f"Decision: {snapshot.human_review.status.value}")
        st.write(f"Reviewer: {snapshot.human_review.reviewer_id}")
        if snapshot.human_review.reviewed_at is not None:
            st.write(f"Reviewed at: {format_timestamp(snapshot.human_review.reviewed_at)}")
        if snapshot.human_review.reason:
            st.write(f"Reason: {snapshot.human_review.reason}")


def _render_review_form(
    snapshot: InvestigationSnapshot,
    service: InvestigationServiceLike | None,
) -> None:
    st.subheader("Human Review")
    with st.form("human-review-form"):
        reviewer_id = st.text_input("Reviewer identifier")
        decision = st.radio("Decision", ["APPROVE", "REJECT"], horizontal=True)
        reason = st.text_area("Reason", value="", max_chars=2_000)
        submitted = st.form_submit_button("Submit review")
    if not submitted:
        return
    if not reviewer_id.strip():
        st.error("Reviewer identifier is required.")
        return
    if decision == "REJECT" and not reason.strip():
        st.error("A rejection reason is required.")
        return
    resolved_service = _investigation_service(service)
    if resolved_service is None:
        st.error("Investigation workflow is unavailable until configuration is complete.")
        return
    with st.spinner("Submitting review"):
        try:
            reviewed = resolved_service.submit_review(
                SubmitHumanReviewRequest(
                    investigation_id=snapshot.investigation_id,
                    thread_id=snapshot.thread_id,
                    decision=HumanReviewDecision(decision),
                    reviewer_id=reviewer_id,
                    reviewed_at=datetime.now(UTC),
                    reason=reason or None,
                )
            )
        except (AgentError, ValidationError) as exc:
            st.error(safe_error_message(exc))
            return
    st.session_state[ACTIVE_INVESTIGATION_STATE_KEY] = reviewed
    st.success("Review submitted.")
    st.rerun()


def _write_list(title: str, values: tuple[str, ...]) -> None:
    st.markdown(f"**{title}**")
    for value in values:
        st.write(f"- {value}")


def _write_findings(report: InvestigationReport) -> None:
    st.markdown("**Evidence findings**")
    for finding in report.evidence_findings:
        keys = ", ".join(finding.evidence_keys) if finding.evidence_keys else "No evidence cited"
        st.write(f"- {finding.finding} ({keys})")


def _selected_supplier_index(supplier_ids: list[str]) -> int:
    selected = st.session_state.get(SELECTED_SUPPLIER_STATE_KEY)
    if isinstance(selected, str) and selected in supplier_ids:
        return supplier_ids.index(selected)
    return 0


def _supplier_label(rows: tuple[PortfolioSupplierRiskRow, ...], supplier_id: str) -> str:
    row = next(item for item in rows if item.supplier_id == supplier_id)
    return f"{row.supplier_id} - {row.supplier_name}"


def _active_investigation() -> InvestigationSnapshot | None:
    active = st.session_state.get(ACTIVE_INVESTIGATION_STATE_KEY)
    return active if isinstance(active, InvestigationSnapshot) else None


def _session_portfolio_service() -> PortfolioDataServiceLike | None:
    service = st.session_state.get("portfolio_service")
    return cast(PortfolioDataServiceLike, service) if service is not None else None


def _safe_portfolio_service() -> PortfolioDataServiceLike | None:
    try:
        return portfolio_service_resource()
    except (AgentConfigurationError, AgentPersistenceError, AgentDataError):
        return None


def _agent_data_service(service: AgentDataServiceLike | None) -> AgentDataServiceLike | None:
    if service is not None:
        return service
    injected = st.session_state.get("agent_data_service")
    if injected is not None:
        return cast(AgentDataServiceLike, injected)
    try:
        return agent_data_service_resource()
    except (AgentConfigurationError, AgentDataError):
        return None


def _investigation_service(
    service: InvestigationServiceLike | None,
) -> InvestigationServiceLike | None:
    if service is not None:
        return service
    injected = st.session_state.get("investigation_service")
    if injected is not None:
        return cast(InvestigationServiceLike, injected)
    try:
        return investigation_service_resource()
    except (AgentConfigurationError, AgentPersistenceError, AgentDataError, AgentError):
        return None


if __name__ == "__main__":
    main()
