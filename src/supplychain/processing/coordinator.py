"""Safe one-message processing coordinator for validated Canonical Events."""

from __future__ import annotations

import time
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from opentelemetry.trace import Span

from supplychain.contracts import CanonicalEvent
from supplychain.messaging import ReceivedCanonicalEvent
from supplychain.observability import ObservabilityRuntime, bind_observability_context
from supplychain.observability.runtime import TelemetryOutcome, elapsed_ms
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
        observability: ObservabilityRuntime | None = None,
    ) -> None:
        self._ledger = ledger
        self._handler = handler
        self._acknowledger = acknowledger
        self._observability = observability or ObservabilityRuntime.disabled()

    def process(self, received_event: ReceivedCanonicalEvent) -> ProcessingCoordinatorResult:
        """Process one already-valid pulled Canonical Event delivery."""

        event = received_event.event
        started_at = time.perf_counter()
        with (
            bind_observability_context(
                correlation_id=event.metadata.correlation_id,
                event_id=event.event_id,
                generate_request_id=True,
            ),
            self._observability.span(
                "supplychain.event.process",
                attributes={
                    "component": "processing",
                    "operation": "process_event",
                    "event_id": str(event.event_id),
                },
            ) as span,
        ):
            try:
                result = self._process_without_telemetry(received_event)
            except Exception:
                self._record_processing(
                    outcome=TelemetryOutcome.FAILURE,
                    processing_decision="exception",
                    started_at=started_at,
                    span=span,
                )
                raise
            self._record_processing(
                outcome=TelemetryOutcome.SUCCESS,
                processing_decision=result.resolution.value,
                started_at=started_at,
                span=span,
            )
            return result

    def _process_without_telemetry(
        self,
        received_event: ReceivedCanonicalEvent,
    ) -> ProcessingCoordinatorResult:
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

    def _record_processing(
        self,
        *,
        outcome: str,
        processing_decision: str,
        started_at: float,
        span: Span | None,
    ) -> None:
        self._observability.record_operation(
            component="processing",
            operation="process_event",
            outcome=outcome,
            duration_ms=elapsed_ms(started_at),
            attributes={"processing_decision": processing_decision},
        )
        self._observability.set_span_status(span, outcome)

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
