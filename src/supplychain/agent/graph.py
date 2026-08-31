"""LangGraph supplier investigation workflow."""

from __future__ import annotations

import json
from collections.abc import Callable, MutableMapping
from datetime import datetime
from typing import Any, Protocol, cast
from uuid import UUID

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph
from langgraph.types import Command, interrupt
from pydantic import BaseModel, ValidationError

from supplychain.agent.context import (
    InvestigationContextLimits,
    build_investigation_context,
)
from supplychain.agent.data import (
    AgentDataError,
    AgentDataService,
    RiskEvidenceInput,
    RiskHistoryInput,
    SupplierLookupInput,
)
from supplychain.agent.errors import AgentError, InvestigationModelError
from supplychain.agent.llm import InvestigationModel
from supplychain.agent.models import (
    HumanReviewInterruptPayload,
    HumanReviewRecord,
    HumanReviewStatus,
    InvestigationState,
    InvestigationStatus,
    SubmitHumanReviewRequest,
    snapshot_from_state,
)
from supplychain.agent.prompts import INVESTIGATION_PROMPT_VERSION
from supplychain.agent.reports import (
    InvestigationAnalysis,
    InvestigationReport,
)
from supplychain.agent.validation import InvestigationReportValidator
from supplychain.contracts import CanonicalEvent
from supplychain.domain import Supplier
from supplychain.risk import SupplierRiskAssessment
from supplychain.risk.models import EvidenceKey

Checkpointer = BaseCheckpointSaver[Any]


class CompiledInvestigationGraph(Protocol):
    """Subset of compiled graph behavior used by the service boundary."""

    def invoke(
        self,
        input: InvestigationState | Command[Any],
        config: MutableMapping[str, Any],
    ) -> dict[str, Any]:
        """Run the graph for one investigation thread."""

    def get_state(self, config: MutableMapping[str, Any]) -> Any:
        """Return the latest LangGraph state snapshot for a thread."""


def build_investigation_graph(
    checkpointer: Checkpointer,
    *,
    data_service: AgentDataService | None = None,
    model: InvestigationModel | None = None,
    context_limits: InvestigationContextLimits | None = None,
    history_limit: int = 5,
    now: Callable[[], datetime] | None = None,
) -> CompiledInvestigationGraph:
    """Compile the investigation graph with explicit dependencies."""

    graph = StateGraph(InvestigationState)
    graph.add_node("initialize_investigation", initialize_investigation)
    graph.add_edge(START, "initialize_investigation")
    if data_service is None or model is None:
        graph.add_node("prepare_investigation", prepare_investigation)
        graph.add_edge("initialize_investigation", "prepare_investigation")
        graph.add_edge("prepare_investigation", END)
    else:
        graph.add_node(
            "load_supplier_context",
            lambda state: load_supplier_context(state, data_service),
        )
        graph.add_node(
            "load_risk_context",
            lambda state: load_risk_context(state, data_service),
        )
        graph.add_node(
            "load_risk_history",
            lambda state: load_risk_history(state, data_service, history_limit),
        )
        graph.add_node(
            "load_evidence",
            lambda state: load_evidence(state, data_service),
        )
        graph.add_node(
            "analyze_investigation",
            lambda state: analyze_investigation(
                state,
                model,
                context_limits=(
                    InvestigationContextLimits() if context_limits is None else context_limits
                ),
                now=now,
            ),
        )
        graph.add_node("finalize_investigation", finalize_investigation)
        graph.add_node("validate_report", validate_report)
        graph.add_node("human_review", human_review)
        graph.add_node("finalize_review", finalize_review)
        graph.add_edge("initialize_investigation", "load_supplier_context")
        graph.add_edge("load_supplier_context", "load_risk_context")
        graph.add_edge("load_risk_context", "load_risk_history")
        graph.add_edge("load_risk_history", "load_evidence")
        graph.add_edge("load_evidence", "analyze_investigation")
        graph.add_edge("analyze_investigation", "finalize_investigation")
        graph.add_edge("finalize_investigation", "validate_report")
        graph.add_edge("validate_report", "human_review")
        graph.add_edge("human_review", "finalize_review")
        graph.add_edge("finalize_review", END)
    return cast(CompiledInvestigationGraph, graph.compile(checkpointer=checkpointer))


def initialize_investigation(state: InvestigationState) -> InvestigationState:
    """Validate durable investigation context before checkpointing."""

    snapshot = snapshot_from_state(state)
    return {
        **state,
        "investigation_id": str(snapshot.investigation_id),
        "thread_id": str(snapshot.thread_id),
        "supplier_id": snapshot.supplier_id,
        "question": snapshot.question,
        "status": InvestigationStatus.CREATED.value,
        "created_at": state["created_at"],
        "updated_at": state["updated_at"],
        "evidence_keys": [],
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
        "validation_result": None,
        "human_review_status": HumanReviewStatus.NOT_REQUESTED.value,
        "human_review": None,
    }


def prepare_investigation(state: InvestigationState) -> InvestigationState:
    """Mark the persisted thread ready for future evidence retrieval stages."""

    snapshot_from_state(state)
    return {
        **state,
        "status": InvestigationStatus.READY.value,
        "updated_at": state["updated_at"],
        "evidence_keys": list(dict.fromkeys(state["evidence_keys"])),
        "supplier_profile": state.get("supplier_profile"),
        "current_risk": state.get("current_risk"),
        "risk_history": list(state.get("risk_history", [])),
        "evidence": list(state.get("evidence", [])),
        "report": state.get("report"),
        "error_code": None,
        "error_message": None,
        "provider_failure_category": None,
        "provider_exception_class": None,
        "provider_status_code": None,
        "validation_result": state.get("validation_result"),
        "human_review_status": state.get(
            "human_review_status",
            HumanReviewStatus.NOT_REQUESTED.value,
        ),
        "human_review": state.get("human_review"),
    }


def load_supplier_context(
    state: InvestigationState,
    data_service: AgentDataService,
) -> InvestigationState:
    """Load the authoritative Supplier profile from CORE."""

    if _is_failed(state):
        return state
    try:
        supplier = data_service.get_supplier_profile(
            SupplierLookupInput(supplier_id=state["supplier_id"])
        )
    except AgentDataError as exc:
        return _failed_state(state, code=type(exc).__name__, message="Supplier retrieval failed")
    return {**state, "supplier_profile": supplier.model_dump(mode="json")}


def load_risk_context(
    state: InvestigationState,
    data_service: AgentDataService,
) -> InvestigationState:
    """Load the authoritative current risk assessment from MART."""

    if _is_failed(state):
        return state
    try:
        risk = data_service.get_current_supplier_risk(
            SupplierLookupInput(supplier_id=state["supplier_id"])
        )
    except AgentDataError as exc:
        return _failed_state(
            state,
            code=type(exc).__name__,
            message="Current risk retrieval failed",
        )
    return {
        **state,
        "current_risk": risk.model_dump(mode="json"),
        "evidence_keys": list(risk.evidence_deduplication_keys),
    }


def load_risk_history(
    state: InvestigationState,
    data_service: AgentDataService,
    history_limit: int,
) -> InvestigationState:
    """Load bounded risk history from MART."""

    if _is_failed(state):
        return state
    try:
        history = data_service.get_supplier_risk_history(
            RiskHistoryInput(supplier_id=state["supplier_id"], limit=history_limit)
        )
    except (AgentDataError, ValidationError) as exc:
        return _failed_state(
            state,
            code=type(exc).__name__,
            message="Risk history retrieval failed",
        )
    return {**state, "risk_history": [item.model_dump(mode="json") for item in history]}


def load_evidence(
    state: InvestigationState,
    data_service: AgentDataService,
) -> InvestigationState:
    """Load canonical evidence from CORE by MART-provided evidence identities."""

    if _is_failed(state):
        return state
    try:
        evidence = data_service.get_risk_evidence(
            RiskEvidenceInput(evidence_deduplication_keys=tuple(state["evidence_keys"]))
        )
    except (AgentDataError, ValidationError) as exc:
        return _failed_state(
            state,
            code=type(exc).__name__,
            message="Risk evidence retrieval failed",
        )
    return {**state, "evidence": [item.model_dump(mode="json") for item in evidence]}


def analyze_investigation(
    state: InvestigationState,
    model: InvestigationModel,
    *,
    context_limits: InvestigationContextLimits,
    now: Callable[[], datetime] | None,
) -> InvestigationState:
    """Run Gemini analysis over bounded context and construct the final report."""

    if _is_failed(state):
        return state
    try:
        supplier = _state_model(Supplier, state.get("supplier_profile"))
        current_risk = _state_model(SupplierRiskAssessment, state.get("current_risk"))
        risk_history = tuple(
            _state_model(SupplierRiskAssessment, item) for item in state.get("risk_history", [])
        )
        evidence = tuple(_state_model(CanonicalEvent, item) for item in state.get("evidence", []))
        context = build_investigation_context(
            question=state["question"],
            supplier=supplier,
            current_risk=current_risk,
            risk_history=risk_history,
            evidence=evidence,
            prompt_version=INVESTIGATION_PROMPT_VERSION,
            limits=context_limits,
        )
        analysis = model.analyze(context)
        allowed_keys = {event.metadata.deduplication_key for event in evidence}
        report = _report_from_analysis(
            state=state,
            risk=current_risk,
            analysis=analysis,
            allowed_evidence_keys=tuple(sorted(allowed_keys)),
            generated_at=(
                now()
                if now is not None
                else datetime.fromisoformat(state["updated_at"].replace("Z", "+00:00"))
            ),
        )
    except (
        AgentError,
        ValidationError,
        ValueError,
        KeyError,
        TypeError,
    ) as exc:
        return _failed_state(
            state,
            code=type(exc).__name__,
            message="Investigation analysis failed",
            provider_error=exc if isinstance(exc, InvestigationModelError) else None,
        )
    return {**state, "report": report.model_dump(mode="json")}


def finalize_investigation(state: InvestigationState) -> InvestigationState:
    """Finalize successful investigation state."""

    if _is_failed(state):
        return state
    if state.get("report") is None:
        return _failed_state(
            state,
            code="MissingReport",
            message="Investigation report was not produced",
        )
    snapshot_from_state(state)
    return {
        **state,
        "status": InvestigationStatus.COMPLETED.value,
        "error_code": None,
        "error_message": None,
    }


def validate_report(state: InvestigationState) -> InvestigationState:
    """Validate the produced report before requesting human review."""

    if _is_failed(state):
        return state
    try:
        snapshot = snapshot_from_state(state)
        if snapshot.report is None:
            return _failed_state(
                state,
                code="MissingReport",
                message="Investigation report was not produced",
            )
        current_risk = _state_model(SupplierRiskAssessment, state.get("current_risk"))
        evidence = tuple(_state_model(CanonicalEvent, item) for item in state.get("evidence", []))
        validation = InvestigationReportValidator().validate(
            report=snapshot.report,
            current_risk=current_risk,
            evidence=evidence,
            supplier_id=snapshot.supplier_id,
            investigation_id=snapshot.investigation_id,
            thread_id=snapshot.thread_id,
            expected_thread_id=snapshot.thread_id,
        )
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        return _failed_state(
            state,
            code=type(exc).__name__,
            message="Investigation report validation failed",
        )
    if not validation.passed:
        return {
            **_failed_state(
                state,
                code="InvestigationReportValidationError",
                message="Investigation report validation failed",
            ),
            "validation_result": validation.model_dump(mode="json"),
            "human_review_status": HumanReviewStatus.NOT_REQUESTED.value,
            "human_review": None,
        }
    pending_review = HumanReviewRecord(status=HumanReviewStatus.PENDING)
    return {
        **state,
        "validation_result": validation.model_dump(mode="json"),
        "human_review_status": HumanReviewStatus.PENDING.value,
        "human_review": pending_review.model_dump(mode="json"),
    }


def human_review(state: InvestigationState) -> InvestigationState:
    """Pause the graph for native LangGraph human review."""

    if _is_failed(state) or state.get("human_review_status") != HumanReviewStatus.PENDING.value:
        return state
    try:
        snapshot = snapshot_from_state(state)
        if snapshot.report is None or snapshot.validation_result is None:
            return _failed_state(
                state,
                code="MissingReviewContext",
                message="Investigation review context was not produced",
            )
        payload = HumanReviewInterruptPayload(
            investigation_id=snapshot.investigation_id,
            thread_id=snapshot.thread_id,
            supplier_id=snapshot.supplier_id,
            risk_score=snapshot.report.risk_score,
            risk_level=snapshot.report.risk_level,
            executive_summary=snapshot.report.executive_summary,
            recommendations=snapshot.report.recommendations,
            evidence_keys=snapshot.report.evidence_deduplication_keys_used,
            validation_passed=snapshot.validation_result.passed,
        )
        review_request = SubmitHumanReviewRequest.model_validate_json(
            json.dumps(interrupt(payload.model_dump(mode="json")), sort_keys=True)
        )
        if (
            review_request.investigation_id != snapshot.investigation_id
            or review_request.thread_id != snapshot.thread_id
        ):
            return _failed_state(
                state,
                code="HumanReviewIdentityMismatch",
                message="Human review identity did not match investigation state",
            )
        review = review_request.to_record()
    except (ValidationError, ValueError, KeyError, TypeError) as exc:
        return _failed_state(
            state,
            code=type(exc).__name__,
            message="Human review submission failed validation",
        )
    return {
        **state,
        "human_review_status": review.status.value,
        "human_review": review.model_dump(mode="json"),
        "error_code": None,
        "error_message": None,
    }


def finalize_review(state: InvestigationState) -> InvestigationState:
    """Finalize post-review graph execution without mutating the report."""

    if _is_failed(state):
        return state
    snapshot_from_state(state)
    return state


def _report_from_analysis(
    *,
    state: InvestigationState,
    risk: SupplierRiskAssessment,
    analysis: InvestigationAnalysis,
    allowed_evidence_keys: tuple[EvidenceKey, ...],
    generated_at: datetime,
) -> InvestigationReport:
    return InvestigationReport(
        investigation_id=UUID(state["investigation_id"]),
        supplier_id=risk.supplier_id,
        generated_at=generated_at,
        risk_score=risk.risk_score,
        risk_level=risk.risk_level,
        risk_model_version=risk.model_version,
        structural_score=risk.structural_score,
        weather_score=risk.weather_score,
        seismic_score=risk.seismic_score,
        dominant_factor=risk.dominant_factor,
        factor_scores=risk.structural,
        executive_summary=analysis.executive_summary,
        key_drivers=analysis.key_drivers,
        evidence_findings=analysis.evidence_findings,
        uncertainties=analysis.uncertainties,
        recommendations=analysis.recommendations,
        evidence_deduplication_keys_used=allowed_evidence_keys,
    )


def _state_model[ModelT: BaseModel](model_type: type[ModelT], value: object) -> ModelT:
    if not isinstance(value, dict):
        raise ValueError("required investigation state field is missing")
    return model_type.model_validate_json(json.dumps(value, sort_keys=True))


def _is_failed(state: InvestigationState) -> bool:
    return state.get("status") == InvestigationStatus.FAILED.value


def _failed_state(
    state: InvestigationState,
    *,
    code: str,
    message: str,
    provider_error: InvestigationModelError | None = None,
) -> InvestigationState:
    provider_failure = None if provider_error is None else provider_error.provider_failure
    return {
        **state,
        "status": InvestigationStatus.FAILED.value,
        "report": None,
        "error_code": code,
        "error_message": message,
        "provider_failure_category": (
            None if provider_failure is None else provider_failure.category.value
        ),
        "provider_exception_class": (
            None if provider_failure is None else provider_failure.exception_class
        ),
        "provider_status_code": None if provider_failure is None else provider_failure.status_code,
    }
