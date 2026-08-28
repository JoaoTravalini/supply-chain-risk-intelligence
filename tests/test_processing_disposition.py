from __future__ import annotations

from datetime import UTC, datetime
from uuid import UUID

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
    NonRetryableProcessingError,
    ProcessedLedgerRecord,
    ProcessingDisposition,
    ProcessingFailureKind,
    ProcessingLedger,
    ProcessingResolution,
    ProcessingResolutionResult,
    ProcessingRuntimeCoordinator,
    RetryableProcessingError,
    determine_failure_disposition,
)

DEFAULT_EVENT_ID = UUID("ba6cae58-865e-4d73-9da4-e60a04546ad2")


class RecordingLedger:
    def __init__(
        self,
        *,
        assess_result: ProcessingResolutionResult,
        record_success_result: ProcessingResolutionResult | None = None,
    ) -> None:
        self.assess_result = assess_result
        self.record_success_result = record_success_result
        self.assessed_events: list[CanonicalEvent] = []
        self.recorded_events: list[CanonicalEvent] = []

    def assess(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        self.assessed_events.append(event)
        return self.assess_result

    def record_success(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        self.recorded_events.append(event)
        if self.record_success_result is None:
            raise AssertionError("record_success_result was not configured")
        return self.record_success_result

    def get_record(self, deduplication_key: str) -> ProcessedLedgerRecord | None:
        _ = deduplication_key
        return None

    def close(self) -> None:
        return None


class RecordingHandler:
    def __init__(self, failure: Exception | None = None) -> None:
        self.failure = failure
        self.handled_events: list[CanonicalEvent] = []

    def handle(self, event: CanonicalEvent) -> None:
        self.handled_events.append(event)
        if self.failure is not None:
            raise self.failure


class RecordingTransport:
    def __init__(self, *, ack_failure: Exception | None = None) -> None:
        self.ack_failure = ack_failure
        self.acknowledged_messages: list[tuple[ReceivedCanonicalEvent, ...]] = []
        self.redelivered_messages: list[tuple[ReceivedCanonicalEvent, ...]] = []
        self.published_messages: list[CanonicalEvent] = []

    def acknowledge(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        self.acknowledged_messages.append(received_messages)
        if self.ack_failure is not None:
            raise self.ack_failure

    def request_redelivery(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        self.redelivered_messages.append(received_messages)


def make_event(event_id: UUID = DEFAULT_EVENT_ID) -> CanonicalEvent:
    event_time = datetime(2026, 8, 27, 12, 0, tzinfo=UTC)
    source = SourceMetadata(
        provider="synthetic-operational",
        endpoint="synthetic://processing-disposition",
        source_event_id="processing-disposition-001",
    )
    return CanonicalEvent(
        event_id=event_id,
        event_type=EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED,
        event_time=event_time,
        ingested_at=datetime(2026, 8, 27, 12, 1, tzinfo=UTC),
        source=source,
        payload={"status": "nominal", "on_time_delivery_pct": 97.0},
        metadata=EventMetadata(
            correlation_id="corr-processing-disposition-001",
            producer="processing-disposition-test",
            producer_version="1.0.0",
            deduplication_key=generate_deduplication_key(
                source=source,
                event_type=EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED,
                event_time=event_time,
            ),
        ),
    )


def make_received_event(
    *,
    event: CanonicalEvent | None = None,
    delivery_attempt: int | None = 1,
) -> ReceivedCanonicalEvent:
    return ReceivedCanonicalEvent(
        event=make_event() if event is None else event,
        message_id="pubsub-message-processing-disposition",
        ack_id="pubsub-ack-processing-disposition",
        delivery_attempt=delivery_attempt,
    )


def make_result(
    resolution: ProcessingResolution,
    event: CanonicalEvent,
) -> ProcessingResolutionResult:
    return ProcessingResolutionResult(
        resolution=resolution,
        deduplication_key=event.metadata.deduplication_key,
        source_content_fingerprint="sha256:processing-disposition-test-fingerprint",
    )


def make_runtime(
    *,
    ledger: ProcessingLedger,
    handler: RecordingHandler,
    transport: RecordingTransport,
    max_delivery_attempts: int = 5,
) -> ProcessingRuntimeCoordinator:
    return ProcessingRuntimeCoordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=transport,
        redelivery_requester=transport,
        max_delivery_attempts=max_delivery_attempts,
    )


@pytest.mark.parametrize(
    ("failure_kind", "delivery_attempt", "expected"),
    [
        (ProcessingFailureKind.RETRYABLE, 1, ProcessingDisposition.REDELIVER),
        (ProcessingFailureKind.RETRYABLE, 5, ProcessingDisposition.DEAD_LETTER),
        (ProcessingFailureKind.RETRYABLE, None, ProcessingDisposition.REDELIVER),
        (ProcessingFailureKind.UNEXPECTED, 1, ProcessingDisposition.REDELIVER),
        (ProcessingFailureKind.UNEXPECTED, 5, ProcessingDisposition.DEAD_LETTER),
        (ProcessingFailureKind.UNEXPECTED, None, ProcessingDisposition.REDELIVER),
        (ProcessingFailureKind.NON_RETRYABLE, 1, ProcessingDisposition.DEAD_LETTER),
        (ProcessingFailureKind.REVISION_CONFLICT, 1, ProcessingDisposition.DEAD_LETTER),
    ],
)
def test_failure_disposition_policy(
    failure_kind: ProcessingFailureKind,
    delivery_attempt: int | None,
    expected: ProcessingDisposition,
) -> None:
    assert (
        determine_failure_disposition(failure_kind, delivery_attempt=delivery_attempt) is expected
    )


@pytest.mark.parametrize("delivery_attempt", [0, -1])
def test_invalid_delivery_attempt_is_rejected(delivery_attempt: int) -> None:
    with pytest.raises(ValueError):
        determine_failure_disposition(
            ProcessingFailureKind.RETRYABLE,
            delivery_attempt=delivery_attempt,
        )


def test_classification_remains_distinct_from_disposition() -> None:
    assert {item.value for item in ProcessingFailureKind}.isdisjoint(
        {item.value for item in ProcessingDisposition}
    )


def test_retryable_handler_failure_requests_one_redelivery_below_budget() -> None:
    event = make_event()
    received = make_received_event(event=event, delivery_attempt=1)
    ledger = RecordingLedger(assess_result=make_result(ProcessingResolution.NEW, event))
    handler = RecordingHandler(RetryableProcessingError("temporary"))
    transport = RecordingTransport()

    result = make_runtime(ledger=ledger, handler=handler, transport=transport).process(received)

    assert result.failure is not None
    assert result.failure.kind is ProcessingFailureKind.RETRYABLE
    assert result.disposition is ProcessingDisposition.REDELIVER
    assert ledger.recorded_events == []
    assert transport.acknowledged_messages == []
    assert transport.redelivered_messages == [(received,)]
    assert handler.handled_events == [event]
    assert transport.published_messages == []


def test_unexpected_handler_failure_uses_bounded_redelivery_without_message_leakage() -> None:
    event = make_event()
    received = make_received_event(event=event, delivery_attempt=1)
    ledger = RecordingLedger(assess_result=make_result(ProcessingResolution.NEW, event))
    handler = RecordingHandler(RuntimeError("raw failure detail must not become metadata"))
    transport = RecordingTransport()

    result = make_runtime(ledger=ledger, handler=handler, transport=transport).process(received)

    assert result.failure is not None
    assert result.failure.kind is ProcessingFailureKind.UNEXPECTED
    assert result.failure.exception_type == "RuntimeError"
    assert "raw failure detail" not in str(result.failure)
    assert result.disposition is ProcessingDisposition.REDELIVER
    assert handler.handled_events == [event]
    assert transport.redelivered_messages == [(received,)]


def test_non_retryable_handler_failure_has_dead_letter_intent_without_ack_success() -> None:
    event = make_event()
    received = make_received_event(event=event, delivery_attempt=1)
    ledger = RecordingLedger(assess_result=make_result(ProcessingResolution.NEW, event))
    handler = RecordingHandler(NonRetryableProcessingError("permanent"))
    transport = RecordingTransport()

    result = make_runtime(ledger=ledger, handler=handler, transport=transport).process(received)

    assert result.failure is not None
    assert result.failure.kind is ProcessingFailureKind.NON_RETRYABLE
    assert result.disposition is ProcessingDisposition.DEAD_LETTER
    assert ledger.recorded_events == []
    assert transport.acknowledged_messages == []
    assert handler.handled_events == [event]
    assert transport.redelivered_messages == [(received,)]


def test_revision_conflict_uses_dead_letter_intent_without_handler_or_ledger_mutation() -> None:
    event = make_event()
    received = make_received_event(event=event, delivery_attempt=1)
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.REVISION_CONFLICT, event),
    )
    handler = RecordingHandler()
    transport = RecordingTransport()

    result = make_runtime(ledger=ledger, handler=handler, transport=transport).process(received)

    assert result.failure is not None
    assert result.failure.kind is ProcessingFailureKind.REVISION_CONFLICT
    assert result.disposition is ProcessingDisposition.DEAD_LETTER
    assert handler.handled_events == []
    assert ledger.recorded_events == []
    assert transport.redelivered_messages == [(received,)]


@pytest.mark.parametrize(
    "resolution",
    [
        ProcessingResolution.NEW,
        ProcessingResolution.DUPLICATE,
        ProcessingResolution.STALE_REVISION,
    ],
)
def test_successful_acknowledged_results_get_no_second_transport_action(
    resolution: ProcessingResolution,
) -> None:
    event = make_event()
    received = make_received_event(event=event, delivery_attempt=1)
    ledger = RecordingLedger(
        assess_result=make_result(resolution, event),
        record_success_result=make_result(resolution, event),
    )
    handler = RecordingHandler()
    transport = RecordingTransport()

    result = make_runtime(ledger=ledger, handler=handler, transport=transport).process(received)

    assert result.failure is None
    assert result.disposition is None
    assert result.redelivery_requested is False
    assert transport.acknowledged_messages == [(received,)]
    assert transport.redelivered_messages == []


def test_ack_failure_after_ledger_success_is_not_processing_failure_or_dead_letter() -> None:
    event = make_event()
    received = make_received_event(event=event, delivery_attempt=1)
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        record_success_result=make_result(ProcessingResolution.NEW, event),
    )
    handler = RecordingHandler()
    transport = RecordingTransport(ack_failure=MessageAcknowledgeError("ack failed"))

    with pytest.raises(MessageAcknowledgeError):
        make_runtime(ledger=ledger, handler=handler, transport=transport).process(received)

    assert handler.handled_events == [event]
    assert ledger.recorded_events == [event]
    assert transport.redelivered_messages == []
    assert transport.published_messages == []


def test_ack_failure_redelivery_can_become_duplicate_without_handler_retry() -> None:
    event = make_event()
    first_received = make_received_event(event=event, delivery_attempt=1)
    first_ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        record_success_result=make_result(ProcessingResolution.NEW, event),
    )
    first_handler = RecordingHandler()
    first_transport = RecordingTransport(ack_failure=MessageAcknowledgeError("ack failed"))

    with pytest.raises(MessageAcknowledgeError):
        make_runtime(
            ledger=first_ledger,
            handler=first_handler,
            transport=first_transport,
        ).process(first_received)

    redelivery_event = make_event(event_id=UUID("9cdac560-f7fb-4e43-8400-c0302f482c61"))
    redelivery = make_received_event(event=redelivery_event, delivery_attempt=2)
    duplicate_ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.DUPLICATE, redelivery_event),
    )
    duplicate_handler = RecordingHandler()
    duplicate_transport = RecordingTransport()

    result = make_runtime(
        ledger=duplicate_ledger,
        handler=duplicate_handler,
        transport=duplicate_transport,
    ).process(redelivery)

    assert first_handler.handled_events == [event]
    assert duplicate_handler.handled_events == []
    assert result.failure is None
    assert duplicate_transport.acknowledged_messages == [(redelivery,)]
    assert duplicate_transport.redelivered_messages == []
