"""Pure presentation helpers for the Streamlit application."""

from __future__ import annotations

from datetime import datetime

from supplychain.agent.models import HumanReviewStatus, InvestigationSnapshot, InvestigationStatus
from supplychain.risk import RiskLevel
from supplychain.ui.data import PortfolioSupplierRiskRow


def format_score(value: float) -> str:
    """Format a risk score for display."""

    return f"{value:.2f}"


def format_timestamp(value: datetime) -> str:
    """Format UTC timestamps without exposing Python reprs."""

    return value.isoformat().replace("+00:00", "Z")


def investigation_label(snapshot: InvestigationSnapshot | None) -> str:
    """Map domain investigation and review states to a concise UI label."""

    if snapshot is None:
        return "No active investigation"
    if snapshot.status is InvestigationStatus.FAILED:
        return "FAILED"
    if snapshot.status in {InvestigationStatus.CREATED, InvestigationStatus.READY}:
        return snapshot.status.value
    if snapshot.human_review_status is HumanReviewStatus.PENDING:
        return "COMPLETED - pending human review"
    if snapshot.human_review_status is HumanReviewStatus.APPROVED:
        return "COMPLETED - approved"
    if snapshot.human_review_status is HumanReviewStatus.REJECTED:
        return "COMPLETED - rejected"
    return snapshot.status.value


def risk_level_distribution(rows: tuple[PortfolioSupplierRiskRow, ...]) -> dict[str, int]:
    """Return stable risk-level counts for charting."""

    counts = {level.value: 0 for level in RiskLevel}
    for row in rows:
        counts[row.risk_level.value] += 1
    return counts


def portfolio_table_rows(rows: tuple[PortfolioSupplierRiskRow, ...]) -> list[dict[str, object]]:
    """Convert portfolio rows into table-safe dictionaries."""

    return [
        {
            "Supplier ID": row.supplier_id,
            "Supplier": row.supplier_name,
            "Category": row.category.value,
            "Country": row.country_code,
            "Criticality": row.criticality.value,
            "Risk Score": row.risk_score,
            "Risk Level": row.risk_level.value,
            "Dominant Factor": row.dominant_factor.value,
        }
        for row in rows
    ]


def highest_risk_rows(
    rows: tuple[PortfolioSupplierRiskRow, ...],
    *,
    limit: int = 10,
) -> list[dict[str, object]]:
    """Return top-risk rows for a compact chart."""

    return [{"Supplier": row.supplier_name, "Risk Score": row.risk_score} for row in rows[:limit]]


def safe_error_message(error: Exception) -> str:
    """Map operational exceptions to user-safe presentation text."""

    return f"{type(error).__name__}: operation unavailable. Check configuration and logs."
