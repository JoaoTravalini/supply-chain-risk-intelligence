from __future__ import annotations

from dataclasses import FrozenInstanceError
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
from supplychain.messaging import ReceivedCanonicalEvent
from supplychain.processing import (
    CoordinatorOutcome,
    NonRetryableProcessingError,
    ProcessedLedgerRecord,
    ProcessingConsistencyError,
    ProcessingCoordinator,
    ProcessingCoordinatorResult,
    ProcessingFailure,
    ProcessingFailureKind,
    ProcessingHandlerError,
    ProcessingLedger,
    ProcessingResolution,
    RetryableProcessingError,
    classify_processing_exception,
    classify_revision_conflict,
)
from supplychain.processing.ledger import ProcessingResolutionResult

DEFAULT_EVENT_ID = UUID("6fce26f8-436a-4acb-9f99-8a3c5fdc4d37")


class RecordingLedger:
    def __init__(
        self,
        *,
        assess_result: ProcessingResolutionResult,
        record_success_result: ProcessingResolutionResult,
        calls: list[str],
    ) -> None:
        self.assess_result = assess_result
        self.record_success_result = record_success_result
        self.calls = calls
        self.recorded_events: list[CanonicalEvent] = []

    def assess(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        self.calls.append("assess")
        return self.assess_result

    def record_success(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        self.calls.append("record_success")
        self.recorded_events.append(event)
        return self.record_success_result

    def get_record(self, deduplication_key: str) -> ProcessedLedgerRecord | None:
        _ = deduplication_key
        return None

    def close(self) -> None:
        return None


class RecordingHandler:
    def __init__(self, *, failure: Exception, calls: list[str]) -> None:
        self.failure = failure
        self.calls = calls

    def handle(self, event: CanonicalEvent) -> None:
        _ = event
        self.calls.append("handler")
        raise self.failure


class RecordingAcknowledger:
    def __init__(self, *, calls: list[str]) -> None:
        self.calls = calls
        self.acknowledged_messages: list[tuple[ReceivedCanonicalEvent, ...]] = []
        self.redelivery_requests = 0

    def acknowledge(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        self.calls.append("ack")
        self.acknowledged_messages.append(received_messages)

    def request_redelivery(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        _ = received_messages
        self.redelivery_requests += 1


def make_event(
    *,
    payload: dict[str, str | float | bool] | None = None,
) -> CanonicalEvent:
    event_time = datetime(2026, 8, 25, 13, 0, tzinfo=UTC)
    source = SourceMetadata(
        provider="synthetic-weather",
        endpoint="synthetic://weather/failure-classification",
        source_event_id="weather-failure-001",
    )
    return CanonicalEvent.model_validate(
        {
            "event_id": DEFAULT_EVENT_ID,
            "event_type": EventType.WEATHER_OBSERVATION_RECORDED,
            "event_time": event_time,
            "ingested_at": datetime(2026, 8, 25, 13, 1, tzinfo=UTC),
            "source": source,
            "payload": payload or {"temperature_2m_c": 24.5, "observed": True},
            "metadata": EventMetadata(
                correlation_id="corr-failure-classification-001",
                producer="failure-classification-test",
                producer_version="1.0.0",
                deduplication_key=generate_deduplication_key(
                    source=source,
                    event_type=EventType.WEATHER_OBSERVATION_RECORDED,
                    event_time=event_time,
                ),
            ),
        }
    )


def make_received_event(
    event: CanonicalEvent,
    *,
    ack_id: str = "pubsub-ack-failure-classification",
) -> ReceivedCanonicalEvent:
    return ReceivedCanonicalEvent(
        event=event,
        message_id="pubsub-message-failure-classification",
        ack_id=ack_id,
    )


def make_result(
    resolution: ProcessingResolution,
    event: CanonicalEvent,
) -> ProcessingResolutionResult:
    return ProcessingResolutionResult(
        resolution=resolution,
        deduplication_key=event.metadata.deduplication_key,
        source_content_fingerprint="sha256:failure-classification-test-fingerprint",
    )


def make_coordinator(
    *,
    ledger: ProcessingLedger,
    handler: RecordingHandler,
    acknowledger: RecordingAcknowledger,
) -> ProcessingCoordinator:
    return ProcessingCoordinator(
        ledger=ledger,
        handler=handler,
        acknowledger=acknowledger,
    )


def mutate_failure_kind(failure: ProcessingFailure) -> None:
    failure.kind = ProcessingFailureKind.UNEXPECTED  # type: ignore[misc]


def test_retryable_error_inherits_project_handler_error_base() -> None:
    assert isinstance(RetryableProcessingError("temporary"), ProcessingHandlerError)


def test_non_retryable_error_inherits_project_handler_error_base() -> None:
    assert isinstance(NonRetryableProcessingError("permanent"), ProcessingHandlerError)


def test_retryable_and_non_retryable_errors_remain_distinct() -> None:
    assert not isinstance(RetryableProcessingError("temporary"), NonRetryableProcessingError)
    assert not isinstance(NonRetryableProcessingError("permanent"), RetryableProcessingError)


def test_arbitrary_runtime_error_is_not_converted_into_handler_error() -> None:
    error = RuntimeError("ordinary programming failure")

    assert not isinstance(error, ProcessingHandlerError)
    assert not isinstance(error, RetryableProcessingError)
    assert not isinstance(error, NonRetryableProcessingError)


@pytest.mark.parametrize(
    ("error", "expected_kind"),
    [
        (RetryableProcessingError("downstream timeout"), ProcessingFailureKind.RETRYABLE),
        (
            NonRetryableProcessingError("unsupported business input"),
            ProcessingFailureKind.NON_RETRYABLE,
        ),
        (RuntimeError("runtime failure"), ProcessingFailureKind.UNEXPECTED),
        (ValueError("value failure"), ProcessingFailureKind.UNEXPECTED),
    ],
)
def test_processing_exception_classification_maps_explicit_error_types(
    error: Exception,
    expected_kind: ProcessingFailureKind,
) -> None:
    event = make_event()

    failure = classify_processing_exception(error, event=event)

    assert failure.kind is expected_kind
    assert failure.event_id == event.event_id
    assert failure.deduplication_key == event.metadata.deduplication_key
    assert failure.exception_type == type(error).__name__


def test_classification_does_not_depend_on_exception_message_text() -> None:
    retryable_text = RuntimeError("temporary timeout please retry later")
    non_retryable_text = RuntimeError("permanent unsupported input")

    assert classify_processing_exception(retryable_text).kind is ProcessingFailureKind.UNEXPECTED
    assert classify_processing_exception(non_retryable_text).kind is (
        ProcessingFailureKind.UNEXPECTED
    )


def test_revision_conflict_can_be_classified_from_coordinator_result_without_exception() -> None:
    event = make_event()
    result = ProcessingCoordinatorResult(
        outcome=CoordinatorOutcome.REVISION_CONFLICT,
        resolution=ProcessingResolution.REVISION_CONFLICT,
        event_id=event.event_id,
        deduplication_key=event.metadata.deduplication_key,
        acknowledged=False,
    )

    failure = classify_revision_conflict(result)

    assert failure.kind is ProcessingFailureKind.REVISION_CONFLICT
    assert failure.exception_type is None
    assert failure.event_id == event.event_id
    assert failure.deduplication_key == event.metadata.deduplication_key


def test_revision_conflict_failure_kind_remains_distinct_from_handler_failure_kinds() -> None:
    handler_failure_kinds = {
        ProcessingFailureKind.RETRYABLE,
        ProcessingFailureKind.NON_RETRYABLE,
    }

    assert ProcessingFailureKind.REVISION_CONFLICT not in handler_failure_kinds


def test_revision_conflict_classifier_requires_revision_conflict_result() -> None:
    event = make_event()
    result = ProcessingCoordinatorResult(
        outcome=CoordinatorOutcome.PROCESSED,
        resolution=ProcessingResolution.NEW,
        event_id=event.event_id,
        deduplication_key=event.metadata.deduplication_key,
        acknowledged=True,
    )

    with pytest.raises(ProcessingConsistencyError):
        classify_revision_conflict(result)


def test_failure_result_excludes_payload_ack_id_and_exception_message() -> None:
    event = make_event(payload={"secret_like_payload_value": "synthetic-sensitive-looking"})
    received = make_received_event(event=event, ack_id="pubsub-ack-safe-metadata")
    error = RuntimeError("raw exception message must not be exposed")

    failure = classify_processing_exception(error, event=received.event)
    public_values = (
        str(failure.kind),
        str(failure.event_id),
        str(failure.deduplication_key),
        str(failure.exception_type),
    )

    assert "synthetic-sensitive-looking" not in public_values
    assert received.ack_id not in public_values
    assert "raw exception message must not be exposed" not in public_values
    assert failure.exception_type == "RuntimeError"


def test_processing_failure_result_is_immutable() -> None:
    failure = ProcessingFailure(kind=ProcessingFailureKind.UNEXPECTED)

    with pytest.raises(FrozenInstanceError):
        mutate_failure_kind(failure)


@pytest.mark.parametrize(
    "handler_failure",
    [
        RetryableProcessingError("temporary downstream unavailable"),
        NonRetryableProcessingError("known permanent rejection"),
        RuntimeError("unexpected handler bug"),
    ],
)
def test_coordinator_handler_failures_remain_visible_without_side_effects(
    handler_failure: Exception,
) -> None:
    calls: list[str] = []
    received = make_received_event(make_event())
    event = received.event
    ledger = RecordingLedger(
        assess_result=make_result(ProcessingResolution.NEW, event),
        record_success_result=make_result(ProcessingResolution.NEW, event),
        calls=calls,
    )
    handler = RecordingHandler(failure=handler_failure, calls=calls)
    acknowledger = RecordingAcknowledger(calls=calls)

    with pytest.raises(type(handler_failure)) as exc_info:
        make_coordinator(
            ledger=ledger,
            handler=handler,
            acknowledger=acknowledger,
        ).process(received)

    assert exc_info.value is handler_failure
    assert calls == ["assess", "handler"]
    assert ledger.recorded_events == []
    assert acknowledger.acknowledged_messages == []
    assert acknowledger.redelivery_requests == 0


def test_failure_kind_taxonomy_contains_only_classification_values() -> None:
    assert set(ProcessingFailureKind) == {
        ProcessingFailureKind.RETRYABLE,
        ProcessingFailureKind.NON_RETRYABLE,
        ProcessingFailureKind.REVISION_CONFLICT,
        ProcessingFailureKind.UNEXPECTED,
    }


def test_failure_classification_does_not_read_delivery_attempt() -> None:
    event = make_event()
    received = make_received_event(event)
    error = RetryableProcessingError("temporary")

    first = classify_processing_exception(error, event=received.event)
    second = classify_processing_exception(error, event=received.event)

    assert received.delivery_attempt is None
    assert first == second


def test_revision_conflict_classification_preserves_safe_identity_only() -> None:
    event = make_event()
    result = ProcessingCoordinatorResult(
        outcome=CoordinatorOutcome.REVISION_CONFLICT,
        resolution=ProcessingResolution.REVISION_CONFLICT,
        event_id=event.event_id,
        deduplication_key=event.metadata.deduplication_key,
        acknowledged=False,
    )

    failure = classify_revision_conflict(result)

    assert failure == ProcessingFailure(
        kind=ProcessingFailureKind.REVISION_CONFLICT,
        event_id=event.event_id,
        deduplication_key=event.metadata.deduplication_key,
    )


def test_declared_handler_failure_classification_does_not_replace_exception() -> None:
    error = RetryableProcessingError("do not replace me")

    failure = classify_processing_exception(error)

    assert failure.kind is ProcessingFailureKind.RETRYABLE
    assert isinstance(error, RetryableProcessingError)
