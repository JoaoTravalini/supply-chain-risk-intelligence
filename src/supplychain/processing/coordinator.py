"""Safe one-message processing coordinator for validated Canonical Events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from supplychain.contracts import CanonicalEvent
from supplychain.messaging import ReceivedCanonicalEvent
from supplychain.processing.ledger import (
    ProcessingLedger,
    ProcessingResolution,
    ProcessingResolutionResult,
)


class CanonicalEventHandler(Protocol):
    """Business handler for one already-validated Canonical Event."""

    def handle(self, event: CanonicalEvent) -> None:
        """Process one Canonical Event."""


class MessageAcknowledger(Protocol):
    """Transport acknowledgement boundary used after safe processing decisions."""

    def acknowledge(self, received_messages: tuple[ReceivedCanonicalEvent, ...]) -> None:
        """Acknowledge one or more received Canonical Event deliveries."""


class CoordinatorOutcome(StrEnum):
    """Public processing coordinator outcomes."""

    PROCESSED = "processed"
    DUPLICATE = "duplicate"
    STALE_REVISION = "stale_revision"
    REVISION_CONFLICT = "revision_conflict"


@dataclass(frozen=True, slots=True)
class ProcessingCoordinatorResult:
    """Result for one coordinator decision."""

    outcome: CoordinatorOutcome
    resolution: ProcessingResolution
    event_id: UUID
    deduplication_key: str
    acknowledged: bool


class ProcessingCoordinator:
    """Coordinate ledger assessment, handler execution, ledger success, and ACK."""

    def __init__(
        self,
        *,
        ledger: ProcessingLedger,
        handler: CanonicalEventHandler,
        acknowledger: MessageAcknowledger,
    ) -> None:
        self._ledger = ledger
        self._handler = handler
        self._acknowledger = acknowledger

    def process(self, received_event: ReceivedCanonicalEvent) -> ProcessingCoordinatorResult:
        """Process one already-valid pulled Canonical Event delivery."""

        event = received_event.event
        assessment = self._ledger.assess(event)
        if assessment.resolution is ProcessingResolution.DUPLICATE:
            self._acknowledge(received_event)
            return self._result(
                event=event,
                resolution_result=assessment,
                outcome=CoordinatorOutcome.DUPLICATE,
                acknowledged=True,
            )
        if assessment.resolution is ProcessingResolution.STALE_REVISION:
            self._acknowledge(received_event)
            return self._result(
                event=event,
                resolution_result=assessment,
                outcome=CoordinatorOutcome.STALE_REVISION,
                acknowledged=True,
            )
        if assessment.resolution is ProcessingResolution.REVISION_CONFLICT:
            return self._result(
                event=event,
                resolution_result=assessment,
                outcome=CoordinatorOutcome.REVISION_CONFLICT,
                acknowledged=False,
            )

        self._handler.handle(event)
        record_result = self._ledger.record_success(event)
        outcome = _outcome_for_record_success(record_result.resolution)
        if record_result.resolution is ProcessingResolution.REVISION_CONFLICT:
            return self._result(
                event=event,
                resolution_result=record_result,
                outcome=outcome,
                acknowledged=False,
            )

        self._acknowledge(received_event)
        return self._result(
            event=event,
            resolution_result=record_result,
            outcome=outcome,
            acknowledged=True,
        )

    def _acknowledge(self, received_event: ReceivedCanonicalEvent) -> None:
        self._acknowledger.acknowledge((received_event,))

    def _result(
        self,
        *,
        event: CanonicalEvent,
        resolution_result: ProcessingResolutionResult,
        outcome: CoordinatorOutcome,
        acknowledged: bool,
    ) -> ProcessingCoordinatorResult:
        return ProcessingCoordinatorResult(
            outcome=outcome,
            resolution=resolution_result.resolution,
            event_id=event.event_id,
            deduplication_key=resolution_result.deduplication_key,
            acknowledged=acknowledged,
        )


def _outcome_for_record_success(resolution: ProcessingResolution) -> CoordinatorOutcome:
    if resolution is ProcessingResolution.DUPLICATE:
        return CoordinatorOutcome.DUPLICATE
    if resolution is ProcessingResolution.STALE_REVISION:
        return CoordinatorOutcome.STALE_REVISION
    if resolution is ProcessingResolution.REVISION_CONFLICT:
        return CoordinatorOutcome.REVISION_CONFLICT
    return CoordinatorOutcome.PROCESSED
