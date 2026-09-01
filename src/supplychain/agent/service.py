"""Public investigation service boundary."""

from __future__ import annotations

import time
from collections.abc import Callable, MutableMapping
from datetime import datetime
from typing import Any

from langgraph.types import Command
from opentelemetry.trace import Span
from pydantic import ValidationError

from supplychain.agent.context import InvestigationContextLimits
from supplychain.agent.data import AgentDataService
from supplychain.agent.errors import (
    AgentConfigurationError,
    AgentPersistenceError,
    HumanReviewTransitionError,
    InvestigationNotFoundError,
)
from supplychain.agent.graph import (
    Checkpointer,
    CompiledInvestigationGraph,
    build_investigation_graph,
)
from supplychain.agent.llm import InvestigationModel
from supplychain.agent.models import (
    CreateInvestigationRequest,
    HumanReviewDecision,
    HumanReviewStatus,
    InvestigationIdentity,
    InvestigationSnapshot,
    InvestigationStatus,
    SubmitHumanReviewRequest,
    require_aware_utc,
    snapshot_from_state,
    snapshot_to_state,
    utc_now,
)
from supplychain.observability import ObservabilityRuntime, bind_observability_context
from supplychain.observability.runtime import TelemetryOutcome, elapsed_ms


class InvestigationService:
    """Service facade for durable Stage 13 investigations."""

    def __init__(
        self,
        *,
        checkpointer: Checkpointer,
        data_service: AgentDataService | None = None,
        model: InvestigationModel | None = None,
        context_limits: InvestigationContextLimits | None = None,
        history_limit: int = 5,
        now: Callable[[], datetime] | None = None,
        graph: CompiledInvestigationGraph | None = None,
        investigation_graph: CompiledInvestigationGraph | None = None,
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._observability = observability or ObservabilityRuntime.disabled()
        self._graph = (
            build_investigation_graph(
                checkpointer,
                observability=self._observability,
            )
            if graph is None
            else graph
        )
        self._investigation_graph = investigation_graph
        if self._investigation_graph is None and data_service is not None and model is not None:
            self._investigation_graph = build_investigation_graph(
                checkpointer,
                data_service=data_service,
                model=model,
                context_limits=(
                    InvestigationContextLimits() if context_limits is None else context_limits
                ),
                history_limit=history_limit,
                now=now,
                observability=self._observability,
            )

    def create_investigation(
        self,
        request: CreateInvestigationRequest,
    ) -> InvestigationSnapshot:
        """Create and checkpoint one investigation thread."""

        identity_data: dict[str, object] = {}
        if request.investigation_id is not None:
            identity_data["investigation_id"] = request.investigation_id
        if request.thread_id is not None:
            identity_data["thread_id"] = request.thread_id
        identity = InvestigationIdentity.model_validate(identity_data)
        created_at = require_aware_utc(request.created_at or utc_now())
        initial_snapshot = InvestigationSnapshot(
            investigation_id=identity.investigation_id,
            thread_id=identity.thread_id,
            supplier_id=request.supplier_id,
            question=request.question,
            status=InvestigationStatus.CREATED,
            created_at=created_at,
            updated_at=created_at,
            evidence_keys=(),
            error_message=None,
        )
        try:
            result = self._graph.invoke(
                snapshot_to_state(initial_snapshot),
                thread_config(str(identity.thread_id)),
            )
        except Exception as exc:
            raise AgentPersistenceError("Unable to create investigation state") from exc
        return snapshot_from_state(result)

    def run_investigation(
        self,
        request: CreateInvestigationRequest,
    ) -> InvestigationSnapshot:
        """Run the Stage 15 evidence-grounded investigation workflow."""

        if self._investigation_graph is None:
            raise AgentConfigurationError("Investigation workflow dependencies are not configured")
        initial_snapshot = self._initial_snapshot(request)
        started_at = time.perf_counter()
        with (
            bind_observability_context(
                correlation_id=initial_snapshot.investigation_id,
                investigation_id=initial_snapshot.investigation_id,
                thread_id=initial_snapshot.thread_id,
                generate_request_id=True,
            ),
            self._observability.span(
                "supplychain.investigation.run",
                attributes={
                    "component": "investigation",
                    "operation": "run_investigation",
                    "supplier_id": initial_snapshot.supplier_id,
                    "investigation_id": str(initial_snapshot.investigation_id),
                    "thread_id": str(initial_snapshot.thread_id),
                },
            ) as span,
        ):
            try:
                result = self._investigation_graph.invoke(
                    snapshot_to_state(initial_snapshot),
                    thread_config(str(initial_snapshot.thread_id)),
                )
                snapshot = snapshot_from_state(result)
                outcome = (
                    TelemetryOutcome.SUCCESS
                    if snapshot.status is InvestigationStatus.COMPLETED
                    else TelemetryOutcome.FAILURE
                )
                self._observability.record_operation(
                    component="investigation",
                    operation="run_investigation",
                    outcome=outcome,
                    duration_ms=elapsed_ms(started_at),
                    attributes={
                        "error_category": (
                            snapshot.provider_failure_category.value
                            if snapshot.provider_failure_category is not None
                            else None
                        ),
                    },
                )
                self._observability.set_span_status(span, outcome)
                return snapshot
            except Exception as exc:
                self._observability.record_operation(
                    component="investigation",
                    operation="run_investigation",
                    outcome=TelemetryOutcome.FAILURE,
                    duration_ms=elapsed_ms(started_at),
                    attributes={"error_category": type(exc).__name__},
                )
                self._observability.set_span_status(span, TelemetryOutcome.FAILURE)
                raise AgentPersistenceError("Unable to run investigation workflow") from exc

    def get_investigation_state(self, thread_id: str) -> InvestigationSnapshot:
        """Retrieve the latest persisted state for one LangGraph thread."""

        config = thread_config(thread_id)
        try:
            state_snapshot = self._graph.get_state(config)
        except Exception as exc:
            raise AgentPersistenceError("Unable to retrieve investigation state") from exc
        values = getattr(state_snapshot, "values", None)
        if not values:
            raise InvestigationNotFoundError("Investigation state was not found")
        try:
            return snapshot_from_state(values)
        except (KeyError, TypeError, ValueError, ValidationError) as exc:
            raise AgentPersistenceError("Persisted investigation state is invalid") from exc

    def submit_review(self, request: SubmitHumanReviewRequest) -> InvestigationSnapshot:
        """Submit a human review decision and resume the pending graph interrupt."""

        if self._investigation_graph is None:
            raise AgentConfigurationError("Investigation workflow dependencies are not configured")
        started_at = time.perf_counter()
        with (
            bind_observability_context(
                correlation_id=request.investigation_id,
                investigation_id=request.investigation_id,
                thread_id=request.thread_id,
                generate_request_id=True,
            ),
            self._observability.span(
                "supplychain.review.submit",
                attributes={
                    "component": "review",
                    "operation": "submit_review",
                    "review_decision": request.decision.value,
                    "investigation_id": str(request.investigation_id),
                    "thread_id": str(request.thread_id),
                },
            ) as span,
        ):
            try:
                current = self.get_investigation_state(str(request.thread_id))
                if current.investigation_id != request.investigation_id:
                    self._record_review_transition(
                        "invalid_transition",
                        request.decision.value,
                        started_at,
                        span,
                    )
                    raise HumanReviewTransitionError(
                        "Human review investigation identity did not match"
                    )
                if current.thread_id != request.thread_id:
                    self._record_review_transition(
                        "invalid_transition",
                        request.decision.value,
                        started_at,
                        span,
                    )
                    raise HumanReviewTransitionError("Human review thread identity did not match")
                if current.human_review_status in {
                    HumanReviewStatus.APPROVED,
                    HumanReviewStatus.REJECTED,
                }:
                    if _is_duplicate_review_submission(current, request):
                        self._record_review_transition(
                            "duplicate",
                            request.decision.value,
                            started_at,
                            span,
                        )
                        return current
                    self._record_review_transition(
                        "invalid_transition",
                        request.decision.value,
                        started_at,
                        span,
                    )
                    raise HumanReviewTransitionError("Human review has already been finalized")
                if (
                    current.status is not InvestigationStatus.COMPLETED
                    or current.report is None
                    or current.human_review_status is not HumanReviewStatus.PENDING
                ):
                    self._record_review_transition(
                        "invalid_transition",
                        request.decision.value,
                        started_at,
                        span,
                    )
                    raise HumanReviewTransitionError(
                        "No human review is pending for this investigation"
                    )
                result = self._investigation_graph.invoke(
                    Command(resume=request.model_dump(mode="json")),
                    thread_config(str(request.thread_id)),
                )
                snapshot = snapshot_from_state(result)
                self._record_review_transition(
                    "success",
                    request.decision.value,
                    started_at,
                    span,
                )
                return snapshot
            except HumanReviewTransitionError:
                raise
            except Exception as exc:
                self._record_review_transition(
                    "failure",
                    request.decision.value,
                    started_at,
                    span,
                )
                raise AgentPersistenceError("Unable to submit human review") from exc

    def _initial_snapshot(self, request: CreateInvestigationRequest) -> InvestigationSnapshot:
        identity_data: dict[str, object] = {}
        if request.investigation_id is not None:
            identity_data["investigation_id"] = request.investigation_id
        if request.thread_id is not None:
            identity_data["thread_id"] = request.thread_id
        identity = InvestigationIdentity.model_validate(identity_data)
        created_at = require_aware_utc(request.created_at or utc_now())
        return InvestigationSnapshot(
            investigation_id=identity.investigation_id,
            thread_id=identity.thread_id,
            supplier_id=request.supplier_id,
            question=request.question,
            status=InvestigationStatus.CREATED,
            created_at=created_at,
            updated_at=created_at,
            evidence_keys=(),
            error_message=None,
        )

    def _record_review_transition(
        self,
        outcome: str,
        review_decision: str,
        started_at: float,
        span: Span | None,
    ) -> None:
        self._observability.record_operation(
            component="review",
            operation="submit_review",
            outcome=outcome,
            duration_ms=elapsed_ms(started_at),
            attributes={"review_decision": review_decision},
        )
        self._observability.set_span_status(
            span,
            TelemetryOutcome.SUCCESS if outcome in {"success", "duplicate"} else outcome,
        )


def thread_config(thread_id: str) -> MutableMapping[str, Any]:
    """Build the official LangGraph checkpoint thread configuration."""

    return {"configurable": {"thread_id": thread_id}}


def _is_duplicate_review_submission(
    current: InvestigationSnapshot,
    request: SubmitHumanReviewRequest,
) -> bool:
    if current.human_review is None:
        return False
    expected_status = (
        HumanReviewStatus.APPROVED
        if request.decision is HumanReviewDecision.APPROVE
        else HumanReviewStatus.REJECTED
    )
    return (
        current.human_review.status is expected_status
        and current.human_review.reviewer_id == request.reviewer_id
        and current.human_review.reason == request.reason
    )


def main() -> None:
    """Run a local synthetic persistence smoke against configured PostgreSQL."""

    from supplychain.agent.persistence import checkpoint_store_from_env

    first_question = "Why is this synthetic supplier currently elevated?"
    second_question = "What should be checked for this separate synthetic investigation?"
    with checkpoint_store_from_env() as first_store:
        service = InvestigationService(checkpointer=first_store.checkpointer)
        first = service.create_investigation(
            CreateInvestigationRequest(
                supplier_id="SUP-000001",
                question=first_question,
            )
        )
        first_thread_id = str(first.thread_id)

    with checkpoint_store_from_env() as second_store:
        service = InvestigationService(checkpointer=second_store.checkpointer)
        resumed = service.get_investigation_state(first_thread_id)
        second = service.create_investigation(
            CreateInvestigationRequest(
                supplier_id="SUP-000001",
                question=second_question,
            )
        )
        isolated = service.get_investigation_state(str(second.thread_id))

    if resumed.supplier_id != "SUP-000001" or resumed.question != first_question:
        raise AgentPersistenceError("Resumed investigation state did not match")
    if isolated.thread_id == resumed.thread_id or isolated.question == resumed.question:
        raise AgentPersistenceError("Investigation thread isolation failed")
    print("LangGraph PostgreSQL persistence smoke passed.")
    print(f"first_investigation_id={resumed.investigation_id}")
    print(f"first_thread_id={resumed.thread_id}")
    print(f"second_thread_id={isolated.thread_id}")


if __name__ == "__main__":
    main()
