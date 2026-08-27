"""Processing failure classification without transport disposition."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum
from uuid import UUID

from supplychain.contracts import CanonicalEvent
from supplychain.processing.coordinator import ProcessingCoordinatorResult
from supplychain.processing.decisions import ProcessingConsistencyError, ProcessingError
from supplychain.processing.ledger import ProcessingResolution


class ProcessingHandlerError(ProcessingError):
    """Base class for explicit business handler failures."""


class RetryableProcessingError(ProcessingHandlerError):
    """Handler failure where a later processing attempt may reasonably succeed."""


class NonRetryableProcessingError(ProcessingHandlerError):
    """Handler failure where repeating the same event is not expected to succeed."""


class ProcessingFailureKind(StrEnum):
    """Failure taxonomy independent of transport disposition."""

    RETRYABLE = "retryable"
    NON_RETRYABLE = "non_retryable"
    REVISION_CONFLICT = "revision_conflict"
    UNEXPECTED = "unexpected"


@dataclass(frozen=True, slots=True)
class ProcessingFailure:
    """Safe classification result for a processing failure or semantic condition."""

    kind: ProcessingFailureKind
    event_id: UUID | None = None
    deduplication_key: str | None = None
    exception_type: str | None = None


def classify_processing_exception(
    error: Exception,
    *,
    event: CanonicalEvent | None = None,
) -> ProcessingFailure:
    """Classify an exception raised while processing one valid Canonical Event."""

    if isinstance(error, RetryableProcessingError):
        kind = ProcessingFailureKind.RETRYABLE
    elif isinstance(error, NonRetryableProcessingError):
        kind = ProcessingFailureKind.NON_RETRYABLE
    else:
        kind = ProcessingFailureKind.UNEXPECTED
    return ProcessingFailure(
        kind=kind,
        event_id=None if event is None else event.event_id,
        deduplication_key=None if event is None else event.metadata.deduplication_key,
        exception_type=type(error).__name__,
    )


def classify_revision_conflict(result: ProcessingCoordinatorResult) -> ProcessingFailure:
    """Classify an unresolved revision conflict coordinator result."""

    if result.resolution is not ProcessingResolution.REVISION_CONFLICT:
        raise ProcessingConsistencyError("coordinator result is not a revision conflict")
    return ProcessingFailure(
        kind=ProcessingFailureKind.REVISION_CONFLICT,
        event_id=result.event_id,
        deduplication_key=result.deduplication_key,
    )
