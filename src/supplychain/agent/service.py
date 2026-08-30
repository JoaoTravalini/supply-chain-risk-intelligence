"""Public investigation service boundary."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any

from pydantic import ValidationError

from supplychain.agent.errors import AgentPersistenceError, InvestigationNotFoundError
from supplychain.agent.graph import (
    Checkpointer,
    CompiledInvestigationGraph,
    build_investigation_graph,
)
from supplychain.agent.models import (
    CreateInvestigationRequest,
    InvestigationIdentity,
    InvestigationSnapshot,
    InvestigationStatus,
    require_aware_utc,
    snapshot_from_state,
    snapshot_to_state,
    utc_now,
)


class InvestigationService:
    """Service facade for durable Stage 13 investigations."""

    def __init__(
        self,
        *,
        checkpointer: Checkpointer,
        graph: CompiledInvestigationGraph | None = None,
    ) -> None:
        self._graph = build_investigation_graph(checkpointer) if graph is None else graph

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


def thread_config(thread_id: str) -> MutableMapping[str, Any]:
    """Build the official LangGraph checkpoint thread configuration."""

    return {"configurable": {"thread_id": thread_id}}


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
