"""Bounded processing disposition policy and one-event runtime coordinator."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from supplychain.contracts import CanonicalEvent
from supplychain.messaging import ReceivedCanonicalEvent
from supplychain.messaging.topology import PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS
from supplychain.processing.coordinator import (
    CanonicalEventHandler,
    CoordinatorOutcome,
    MessageAcknowledger,
    ProcessingCoordinator,
    ProcessingCoordinatorResult,
)
from supplychain.processing.failures import (
    ProcessingFailure,
    ProcessingFailureKind,
    classify_processing_exception,
    classify_revision_conflict,
)
from supplychain.processing.ledger import ProcessingLedger


class ProcessingDisposition(StrEnum):
    """Transport/runtime disposition taxonomy for one processing failure."""

    ACK = "ack"
    REDELIVER = "redeliver"
    DEAD_LETTER = "dead_letter"


class RedeliveryRequester(Protocol):
    """Transport boundary for explicit redelivery requests."""

    def request_redelivery(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        """Request redelivery for one or more received Canonical Event deliveries."""


@dataclass(frozen=True, slots=True)
class ProcessingRuntimeResult:
    """Safe result from applying one runtime/disposition decision."""

    event_id: UUID
    deduplication_key: str
    coordinator_result: ProcessingCoordinatorResult | None
    failure: ProcessingFailure | None
    disposition: ProcessingDisposition | None
    redelivery_requested: bool


class ProcessingRuntimeCoordinator:
    """Apply bounded failure disposition around the safe processing coordinator."""

    def __init__(
        self,
        *,
        ledger: ProcessingLedger,
        handler: CanonicalEventHandler,
        acknowledger: MessageAcknowledger,
        redelivery_requester: RedeliveryRequester,
        max_delivery_attempts: int = PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS,
    ) -> None:
        _validate_max_delivery_attempts(max_delivery_attempts)
        self._handler = _ClassifyingHandler(handler)
        self._coordinator = ProcessingCoordinator(
            ledger=ledger,
            handler=self._handler,
            acknowledger=acknowledger,
        )
        self._redelivery_requester = redelivery_requester
        self._max_delivery_attempts = max_delivery_attempts

    def process(self, received_event: ReceivedCanonicalEvent) -> ProcessingRuntimeResult:
        """Process one delivery and apply one disposition when processing fails."""

        try:
            coordinator_result = self._coordinator.process(received_event)
        except Exception as exc:
            if self._handler.failure is not None and self._handler.error is exc:
                return self._apply_failure(
                    received_event=received_event,
                    failure=self._handler.failure,
                )
            raise
        if coordinator_result.acknowledged:
            return ProcessingRuntimeResult(
                event_id=coordinator_result.event_id,
                deduplication_key=coordinator_result.deduplication_key,
                coordinator_result=coordinator_result,
                failure=None,
                disposition=None,
                redelivery_requested=False,
            )
        if coordinator_result.outcome is CoordinatorOutcome.REVISION_CONFLICT:
            return self._apply_failure(
                received_event=received_event,
                failure=classify_revision_conflict(coordinator_result),
                coordinator_result=coordinator_result,
            )
        return ProcessingRuntimeResult(
            event_id=coordinator_result.event_id,
            deduplication_key=coordinator_result.deduplication_key,
            coordinator_result=coordinator_result,
            failure=None,
            disposition=None,
            redelivery_requested=False,
        )

    def _apply_failure(
        self,
        *,
        received_event: ReceivedCanonicalEvent,
        failure: ProcessingFailure,
        coordinator_result: ProcessingCoordinatorResult | None = None,
    ) -> ProcessingRuntimeResult:
        disposition = determine_failure_disposition(
            failure.kind,
            delivery_attempt=received_event.delivery_attempt,
            max_delivery_attempts=self._max_delivery_attempts,
        )
        self._request_redelivery(received_event)
        return ProcessingRuntimeResult(
            event_id=received_event.event.event_id,
            deduplication_key=received_event.event.metadata.deduplication_key,
            coordinator_result=coordinator_result,
            failure=failure,
            disposition=disposition,
            redelivery_requested=True,
        )

    def _request_redelivery(self, received_event: ReceivedCanonicalEvent) -> None:
        self._redelivery_requester.request_redelivery((received_event,))


class _ClassifyingHandler:
    def __init__(self, handler: CanonicalEventHandler) -> None:
        self._handler = handler
        self.error: Exception | None = None
        self.failure: ProcessingFailure | None = None

    def handle(self, event: CanonicalEvent) -> None:
        self.error = None
        self.failure = None
        try:
            self._handler.handle(event)
        except Exception as exc:
            self.error = exc
            self.failure = classify_processing_exception(exc, event=event)
            raise


def determine_failure_disposition(
    failure_kind: ProcessingFailureKind,
    *,
    delivery_attempt: int | None,
    max_delivery_attempts: int = PUBSUB_DEAD_LETTER_MAX_DELIVERY_ATTEMPTS,
) -> ProcessingDisposition:
    """Return the bounded transport/runtime disposition for a failure kind."""

    _validate_max_delivery_attempts(max_delivery_attempts)
    _validate_delivery_attempt(delivery_attempt)
    if failure_kind in {
        ProcessingFailureKind.NON_RETRYABLE,
        ProcessingFailureKind.REVISION_CONFLICT,
    }:
        return ProcessingDisposition.DEAD_LETTER
    if delivery_attempt is None:
        return ProcessingDisposition.REDELIVER
    if delivery_attempt >= max_delivery_attempts:
        return ProcessingDisposition.DEAD_LETTER
    return ProcessingDisposition.REDELIVER


def _validate_delivery_attempt(delivery_attempt: int | None) -> None:
    if delivery_attempt is None:
        return
    if isinstance(delivery_attempt, bool) or not isinstance(delivery_attempt, int):
        raise ValueError("delivery_attempt must be a positive integer when present")
    if delivery_attempt < 1:
        raise ValueError("delivery_attempt must be positive when present")


def _validate_max_delivery_attempts(max_delivery_attempts: int) -> None:
    if isinstance(max_delivery_attempts, bool) or not isinstance(max_delivery_attempts, int):
        raise ValueError("max_delivery_attempts must be an integer")
    if max_delivery_attempts < 5 or max_delivery_attempts > 100:
        raise ValueError("max_delivery_attempts must be between 5 and 100")
