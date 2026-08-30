"""Minimal real LangGraph investigation graph."""

from __future__ import annotations

from collections.abc import MutableMapping
from typing import Any, Protocol, cast

from langgraph.checkpoint.base import BaseCheckpointSaver
from langgraph.graph import END, START, StateGraph

from supplychain.agent.models import (
    InvestigationState,
    InvestigationStatus,
    snapshot_from_state,
)

Checkpointer = BaseCheckpointSaver[Any]


class CompiledInvestigationGraph(Protocol):
    """Subset of compiled graph behavior used by the service boundary."""

    def invoke(
        self,
        input: InvestigationState,
        config: MutableMapping[str, Any],
    ) -> dict[str, Any]:
        """Run the graph for one investigation thread."""

    def get_state(self, config: MutableMapping[str, Any]) -> Any:
        """Return the latest LangGraph state snapshot for a thread."""


def build_investigation_graph(checkpointer: Checkpointer) -> CompiledInvestigationGraph:
    """Compile the Stage 13 investigation graph with an explicit checkpointer."""

    graph = StateGraph(InvestigationState)
    graph.add_node("initialize_investigation", initialize_investigation)
    graph.add_node("prepare_investigation", prepare_investigation)
    graph.add_edge(START, "initialize_investigation")
    graph.add_edge("initialize_investigation", "prepare_investigation")
    graph.add_edge("prepare_investigation", END)
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
        "error_message": None,
    }


def prepare_investigation(state: InvestigationState) -> InvestigationState:
    """Mark the persisted thread ready for future evidence retrieval stages."""

    snapshot_from_state(state)
    return {
        **state,
        "status": InvestigationStatus.READY.value,
        "updated_at": state["updated_at"],
        "evidence_keys": list(dict.fromkeys(state["evidence_keys"])),
        "error_message": None,
    }
