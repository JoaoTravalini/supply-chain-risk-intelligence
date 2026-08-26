from __future__ import annotations

import re
import shutil
from collections.abc import Iterator
from contextlib import suppress
from dataclasses import FrozenInstanceError
from datetime import UTC, datetime
from pathlib import Path
from uuid import UUID, uuid4

import pytest

from supplychain.contracts import (
    CanonicalEvent,
    EventMetadata,
    EventType,
    SourceMetadata,
    generate_deduplication_key,
)
from supplychain.messaging import MessageAcknowledgeError, ReceivedCanonicalEvent
from supplychain.processing import (
    CanonicalEventHandler,
    CoordinatorOutcome,
    MessageAcknowledger,
    ProcessedLedgerRecord,
    ProcessingCoordinator,
    ProcessingCoordinatorResult,
    ProcessingLedger,
    ProcessingResolution,
    ProcessingResolutionResult,
    SqliteProcessingLedger,
)

DEFAULT_EVENT_ID = UUID("f3291625-2d14-4ce8-9d65-95d8848f0df8")


@pytest.fixture
def coordinator_tmp_path(request: pytest.FixtureRequest) -> Iterator[Path]:
    safe_name = re.sub(r"[^A-Za-z0-9_.-]+", "_", request.node.name)
    root = Path(".pytest-coordinator-tests")
    path = root / safe_name
    if path.exists():
        shutil.rmtree(path)
    path.mkdir(parents=True)
    try:
        yield path
    finally:
        shutil.rmtree(path, ignore_errors=True)
        with suppress(OSError):
            root.rmdir()


class RecordingLedger:
    def __init__(
        self,
        *,
        assess_result: ProcessingResolutionResult | None = None,
        record_success_result: ProcessingResolutionResult | None = None,
        assess_failure: Exception | None = None,
        record_success_failure: Exception | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.assess_result = assess_result
        self.record_success_result = record_success_result
        self.assess_failure = assess_failure
        self.record_success_failure = record_success_failure
        self.calls = [] if calls is None else calls
        self.assessed_events: list[CanonicalEvent] = []
        self.recorded_events: list[CanonicalEvent] = []

    def assess(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        self.calls.append("assess")
        self.assessed_events.append(event)
        if self.assess_failure is not None:
            raise self.assess_failure
        if self.assess_result is None:
            raise AssertionError("assess_result was not configured")
        return self.assess_result

    def record_success(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        self.calls.append("record_success")
        self.recorded_events.append(event)
        if self.record_success_failure is not None:
            raise self.record_success_failure
        if self.record_success_result is None:
            raise AssertionError("record_success_result was not configured")
        return self.record_success_result

    def get_record(self, deduplication_key: str) -> ProcessedLedgerRecord | None:
        _ = deduplication_key
        return None

    def close(self) -> None:
        return None


class RecordingHandler:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.failure = failure
        self.calls = [] if calls is None else calls
        self.handled_events: list[CanonicalEvent] = []

    def handle(self, event: CanonicalEvent) -> None:
        self.calls.append("handler")
        self.handled_events.append(event)
        if self.failure is not None:
            raise self.failure


class RecordingAcknowledger:
    def __init__(
        self,
        *,
        failure: Exception | None = None,
        calls: list[str] | None = None,
    ) -> None:
        self.failure = failure
        self.calls = [] if calls is None else calls
        self.acknowledged_messages: list[tuple[ReceivedCanonicalEvent, ...]] = []
        self.redelivery_requests = 0

    def acknowledge(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        self.calls.append("ack")
        self.acknowledged_messages.append(received_messages)
        if self.failure is not None:
            raise self.failure

    def request_redelivery(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        _ = received_messages
        self.redelivery_requests += 1


def make_source(source_event_id: str = "weather-obs-coordinator-001") -> SourceMetadata:
    return SourceMetadata(
        provider="synthetic-weather",
        endpoint="synthetic://weather/reference",
        source_event_id=source_event_id,
    )


def make_event(
    *,
    event_id: UUID = DEFAULT_EVENT_ID,
    source: SourceMetadata | None = None,
    event_time: datetime = datetime(2026, 8, 25, 12, 0, tzinfo=UTC),
    payload: dict[str, float | bool] | None = None,
) -> CanonicalEvent:
    event_source = make_source() if source is None else source
    return CanonicalEvent.model_validate(
        {
            "event_id": event_id,
            "event_type": EventType.WEATHER_OBSERVATION_RECORDED,
            "event_time": event_time,
            "ingested_at": datetime(2026, 8, 25, 12, 1, tzinfo=UTC),
            "source": event_source,
            "payload": payload or {"temperature_2m_c": 21.2, "observed": True},
            "metadata": EventMetadata(
                correlation_id="corr-processing-coordinator-001",
                producer="processing-coordinator-test",
                producer_version="1.0.0",
                deduplication_key=generate_deduplication_key(
                    source=event_source,
                    event_type=EventType.WEATHER_OBSERVATION_RECORDED,
                    event_time=event_time,
                ),
            ),
        }
    )


def make_received_event(
    *,
    event: CanonicalEvent | None = None,
    message_id: str = "pubsub-message-001",
    ack_id: str = "pubsub-ack-001",
) -> ReceivedCanonicalEvent:
    return ReceivedCanonicalEvent(
        event=make_event() if event is None else event,
        message_id=message_id,
        ack_id=ack_id,
    )


def make_result(
    resolution: ProcessingResolution,
    event: CanonicalEvent,
) -> ProcessingResolutionResult:
    return ProcessingResolutionResult(
        resolution=resolution,
        deduplication_key=event.metadata.deduplication_key,
        source_content_fingerprint="sha256:coordinator-test-fingerprint",
    )


def make_coordinator(
    *,
    ledger: ProcessingLedger,
    handler: CanonicalEventHandler,
    acknowledger: MessageAcknowledger,
) -> ProcessingCoordinator:
    return ProcessingCoordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    )


def mutate_acknowledged(result: ProcessingCoordinatorResult) -> None:
    result.acknowledged = False  # type: ignore[misc]


def test_processing_coordinator_public_api_imports() -> None:
    event = make_event()
    result = ProcessingCoordinatorResult(
        outcome=CoordinatorOutcome.PROCESSED,
        resolution=ProcessingResolution.NEW,
        event_id=event.event_id,
        deduplication_key=event.metadata.deduplication_key,
        acknowledged=True,
    )

    assert result.outcome is CoordinatorOutcome.PROCESSED
    assert result.resolution is ProcessingResolution.NEW


@pytest.mark.parametrize(
    ("assessment_resolution", "expected_outcome"),
    [
        (ProcessingResolution.NEW, CoordinatorOutcome.PROCESSED),
        (ProcessingResolution.NEWER_REVISION, CoordinatorOutcome.PROCESSED),
    ],
)
def test_new_or_newer_revision_processes_records_success_then_acknowledges(
    assessment_resolution: ProcessingResolution,
    expected_outcome: CoordinatorOutcome,
) -> None:
    calls: list[str] = []
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(assessment_resolution, event),
        record_success_result=make_result(assessment_resolution, event),
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    result = make_coordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    ).process(received)

    assert calls == ["assess", "handler", "record_success", "ack"]
    assert result.outcome is expected_outcome
    assert result.resolution is assessment_resolution
    assert result.acknowledged is True
    assert acknowledger.acknowledged_messages == [(received,)]


def test_duplicate_short_circuits_handler_and_record_success_then_acknowledges() -> None:
    calls: list[str] = []
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.DUPLICATE, event),
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    result = make_coordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    ).process(received)

    assert calls == ["assess", "ack"]
    assert result.outcome is CoordinatorOutcome.DUPLICATE
    assert result.resolution is ProcessingResolution.DUPLICATE
    assert result.acknowledged is True
    assert handler.handled_events == []
    assert ledger.recorded_events == []


def test_stale_revision_short_circuits_handler_and_ledger_mutation_then_acknowledges() -> None:
    calls: list[str] = []
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.STALE_REVISION, event),
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    result = make_coordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    ).process(received)

    assert calls == ["assess", "ack"]
    assert result.outcome is CoordinatorOutcome.STALE_REVISION
    assert result.acknowledged is True
    assert handler.handled_events == []
    assert ledger.recorded_events == []


def test_revision_conflict_short_circuits_without_ack_or_redelivery_request() -> None:
    calls: list[str] = []
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.REVISION_CONFLICT, event),
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    result = make_coordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    ).process(received)

    assert calls == ["assess"]
    assert result.outcome is CoordinatorOutcome.REVISION_CONFLICT
    assert result.resolution is ProcessingResolution.REVISION_CONFLICT
    assert result.acknowledged is False
    assert handler.handled_events == []
    assert acknowledger.acknowledged_messages == []
    assert acknowledger.redelivery_requests == 0


def test_ledger_assessment_failure_propagates_without_handler_or_ack() -> None:
    calls: list[str] = []
    failure = RuntimeError("ledger assess failed")
    received = make_received_event()
    ledger = RecordingLedger(assess_failure=failure, calls=calls)
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    with pytest.raises(RuntimeError) as exc_info:
        make_coordinator(
            ledger=ledger,
            handler=handler,
            acknowledger=acknowledger,
        ).process(received)

    assert exc_info.value is failure
    assert calls == ["assess"]
    assert handler.handled_events == []
    assert acknowledger.acknowledged_messages == []


def test_handler_failure_propagates_without_record_success_ack_or_redelivery_request() -> None:
    calls: list[str] = []
    failure = RuntimeError("handler failed")
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        calls=calls,
    )
    handler = RecordingHandler(failure=failure, calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    with pytest.raises(RuntimeError) as exc_info:
        make_coordinator(
            ledger=ledger,
            handler=handler,
            acknowledger=acknowledger,
        ).process(received)

    assert exc_info.value is failure
    assert calls == ["assess", "handler"]
    assert ledger.recorded_events == []
    assert acknowledger.acknowledged_messages == []
    assert acknowledger.redelivery_requests == 0


def test_record_success_failure_propagates_without_ack_or_second_handler_call() -> None:
    calls: list[str] = []
    failure = RuntimeError("record success failed")
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        record_success_failure=failure,
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    with pytest.raises(RuntimeError) as exc_info:
        make_coordinator(
            ledger=ledger,
            handler=handler,
            acknowledger=acknowledger,
        ).process(received)

    assert exc_info.value is failure
    assert calls == ["assess", "handler", "record_success"]
    assert handler.handled_events == [event]
    assert acknowledger.acknowledged_messages == []


def test_ack_failure_after_record_success_propagates_without_second_handler_call() -> None:
    calls: list[str] = []
    failure = MessageAcknowledgeError("ack failed")
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        record_success_result=make_result(ProcessingResolution.NEW, event),
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(failure=failure, calls=calls)

    with pytest.raises(MessageAcknowledgeError) as exc_info:
        make_coordinator(
            ledger=ledger,
            handler=handler,
            acknowledger=acknowledger,
        ).process(received)

    assert exc_info.value is failure
    assert calls == ["assess", "handler", "record_success", "ack"]
    assert handler.handled_events == [event]
    assert acknowledger.redelivery_requests == 0


@pytest.mark.parametrize(
    ("record_resolution", "expected_outcome", "expected_acknowledged"),
    [
        (ProcessingResolution.NEW, CoordinatorOutcome.PROCESSED, True),
        (ProcessingResolution.NEWER_REVISION, CoordinatorOutcome.PROCESSED, True),
        (ProcessingResolution.DUPLICATE, CoordinatorOutcome.DUPLICATE, True),
        (ProcessingResolution.STALE_REVISION, CoordinatorOutcome.STALE_REVISION, True),
        (ProcessingResolution.REVISION_CONFLICT, CoordinatorOutcome.REVISION_CONFLICT, False),
    ],
)
def test_post_handler_record_success_resolution_controls_ack_decision(
    record_resolution: ProcessingResolution,
    expected_outcome: CoordinatorOutcome,
    expected_acknowledged: bool,
) -> None:
    calls: list[str] = []
    received = make_received_event()
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        record_success_result=make_result(record_resolution, event),
        calls=calls,
    )
    handler = RecordingHandler(calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    result = make_coordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    ).process(received)

    expected_calls = ["assess", "handler", "record_success"]
    if expected_acknowledged:
        expected_calls.append("ack")
    assert calls == expected_calls
    assert result.outcome is expected_outcome
    assert result.resolution is record_resolution
    assert result.acknowledged is expected_acknowledged


def test_ack_failure_after_persisted_success_redelivers_as_duplicate_without_second_handler_call(
    coordinator_tmp_path: Path,
) -> None:
    path = coordinator_tmp_path / "processing-ledger.sqlite"
    event = make_event()
    first_received = make_received_event(event=event, ack_id="pubsub-ack-first")
    redelivery = make_received_event(
        event=make_event(event_id=uuid4()),
        message_id="pubsub-message-redelivery",
        ack_id="pubsub-ack-redelivery",
    )
    first_handler = RecordingHandler()
    first_acknowledger = RecordingAcknowledger(
        failure=MessageAcknowledgeError("ack failed after ledger success")
    )
    second_handler = RecordingHandler()
    second_acknowledger = RecordingAcknowledger()

    with SqliteProcessingLedger(path) as ledger:
        with pytest.raises(MessageAcknowledgeError):
            ProcessingCoordinator(
                ledger=ledger,
                handler=first_handler,
                acknowledger=first_acknowledger,
            ).process(first_received)

        result = ProcessingCoordinator(
            ledger=ledger,
            handler=second_handler,
            acknowledger=second_acknowledger,
        ).process(redelivery)

    assert len(first_handler.handled_events) == 1
    assert second_handler.handled_events == []
    assert result.outcome is CoordinatorOutcome.DUPLICATE
    assert result.resolution is ProcessingResolution.DUPLICATE
    assert result.acknowledged is True
    assert second_acknowledger.acknowledged_messages == [(redelivery,)]


def test_transport_identifiers_are_not_exposed_as_processing_identity() -> None:
    received = make_received_event(
        message_id="transport-message-that-is-not-business-identity",
        ack_id="transport-ack-that-is-not-business-identity",
    )
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.DUPLICATE, event),
    )
    result = ProcessingCoordinator(
        ledger=ledger,
        handler=RecordingHandler(),
        acknowledger=RecordingAcknowledger(),
    ).process(received)

    assert result.event_id == event.event_id
    assert result.deduplication_key == event.metadata.deduplication_key
    assert not hasattr(result, "message_id")
    assert not hasattr(result, "ack_id")


def test_coordinator_result_is_immutable_after_validation() -> None:
    event = make_event()
    result = ProcessingCoordinatorResult(
        outcome=CoordinatorOutcome.PROCESSED,
        resolution=ProcessingResolution.NEW,
        event_id=event.event_id,
        deduplication_key=event.metadata.deduplication_key,
        acknowledged=True,
    )

    with pytest.raises(FrozenInstanceError):
        mutate_acknowledged(result)
