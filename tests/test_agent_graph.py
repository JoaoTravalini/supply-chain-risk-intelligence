from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

from langgraph.checkpoint.memory import InMemorySaver

from supplychain.agent import build_investigation_graph, thread_config
from supplychain.agent.models import (
    InvestigationSnapshot,
    InvestigationState,
    InvestigationStatus,
    snapshot_from_state,
    snapshot_to_state,
)

CREATED_AT = datetime(2026, 8, 29, 12, 0, tzinfo=UTC)
INVESTIGATION_ID = UUID("11111111-1111-4111-8111-111111111111")
THREAD_ID = UUID("22222222-2222-4222-8222-222222222222")


def make_state() -> InvestigationState:
    snapshot = InvestigationSnapshot(
        investigation_id=INVESTIGATION_ID,
        thread_id=THREAD_ID,
        supplier_id="SUP-000001",
        question="Why is this supplier elevated?",
        status=InvestigationStatus.CREATED,
        created_at=CREATED_AT,
        updated_at=CREATED_AT,
        evidence_keys=(),
    )
    return snapshot_to_state(snapshot)


def test_graph_compiles_and_runs_start_to_end() -> None:
    graph = build_investigation_graph(InMemorySaver())

    result = graph.invoke(make_state(), thread_config(str(THREAD_ID)))
    snapshot = snapshot_from_state(result)

    assert snapshot.status is InvestigationStatus.READY
    assert snapshot.supplier_id == "SUP-000001"
    assert snapshot.question == "Why is this supplier elevated?"
    assert snapshot.investigation_id == INVESTIGATION_ID
    assert snapshot.thread_id == THREAD_ID


def test_graph_uses_langgraph_thread_config_for_checkpoint_identity() -> None:
    graph = build_investigation_graph(InMemorySaver())
    config = thread_config(str(THREAD_ID))

    graph.invoke(make_state(), config)
    persisted = graph.get_state(config)

    assert persisted.config["configurable"]["thread_id"] == str(THREAD_ID)
    assert persisted.values["thread_id"] == str(THREAD_ID)


def test_graph_does_not_calculate_risk_or_fabricate_evidence() -> None:
    graph = build_investigation_graph(InMemorySaver())

    result = graph.invoke(make_state(), thread_config(str(THREAD_ID)))

    assert "risk_score" not in result
    assert "risk_level" not in result
    assert result["evidence_keys"] == []
