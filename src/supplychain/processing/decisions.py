"""Pure processing decision semantics for Canonical Events."""

from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from supplychain.contracts import CanonicalEvent, generate_deduplication_key
from supplychain.processing.fingerprints import generate_source_content_fingerprint


class ProcessingError(Exception):
    """Base exception for processing semantic failures."""


class ProcessingConsistencyError(ProcessingError):
    """Processing comparison input is internally inconsistent."""


class ProcessingDecision(StrEnum):
    """Stage 10A processing decision taxonomy."""

    NEW = "new"
    DUPLICATE = "duplicate"
    REVISION_CANDIDATE = "revision_candidate"


@dataclass(frozen=True, slots=True)
class ProcessedEventRecord:
    """Minimum prior processing state required for Stage 10A comparison."""

    deduplication_key: str
    source_content_fingerprint: str

    def __post_init__(self) -> None:
        if not self.deduplication_key.strip():
            raise ProcessingConsistencyError("prior deduplication key must not be blank")
        if not self.source_content_fingerprint.strip():
            raise ProcessingConsistencyError("prior source content fingerprint must not be blank")


@dataclass(frozen=True, slots=True)
class ProcessingAssessment:
    """Result of pure Stage 10A processing assessment."""

    decision: ProcessingDecision
    deduplication_key: str
    source_content_fingerprint: str
    previous_source_content_fingerprint: str | None = None


def assess_event(
    event: CanonicalEvent,
    previous_record: ProcessedEventRecord | None,
) -> ProcessingAssessment:
    """Classify an event using caller-supplied prior state only."""

    _ensure_event_deduplication_key_is_consistent(event)
    deduplication_key = event.metadata.deduplication_key
    source_content_fingerprint = generate_source_content_fingerprint(event)

    if previous_record is None:
        return ProcessingAssessment(
            decision=ProcessingDecision.NEW,
            deduplication_key=deduplication_key,
            source_content_fingerprint=source_content_fingerprint,
        )

    if previous_record.deduplication_key != deduplication_key:
        raise ProcessingConsistencyError(
            "prior record deduplication key does not match current event"
        )

    if previous_record.source_content_fingerprint == source_content_fingerprint:
        decision = ProcessingDecision.DUPLICATE
    else:
        decision = ProcessingDecision.REVISION_CANDIDATE

    return ProcessingAssessment(
        decision=decision,
        deduplication_key=deduplication_key,
        source_content_fingerprint=source_content_fingerprint,
        previous_source_content_fingerprint=previous_record.source_content_fingerprint,
    )


def _ensure_event_deduplication_key_is_consistent(event: CanonicalEvent) -> None:
    expected = generate_deduplication_key(
        source=event.source,
        event_type=event.event_type,
        event_time=event.event_time,
    )
    if event.metadata.deduplication_key != expected:
        raise ProcessingConsistencyError("event deduplication key is inconsistent")
