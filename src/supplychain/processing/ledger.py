"""Persistent processing ledger abstraction and local SQLite implementation."""

from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass
from datetime import UTC, datetime
from enum import StrEnum
from pathlib import Path
from typing import Protocol
from uuid import UUID

from supplychain.contracts import CanonicalEvent, EventType
from supplychain.processing.decisions import (
    ProcessedEventRecord,
    ProcessingAssessment,
    ProcessingConsistencyError,
    ProcessingDecision,
    assess_event,
)
from supplychain.processing.fingerprints import generate_source_content_fingerprint
from supplychain.processing.revisions import SourceRevision, extract_source_revision

SQLITE_LEDGER_SCHEMA_VERSION = 1
PROCESSED_EVENTS_TABLE = "processed_events"
_FINGERPRINT_PATTERN = re.compile(r"^sha256:[0-9a-f]{64}$")


class ProcessingResolution(StrEnum):
    """Stage 10B ledger-aware processing outcomes."""

    NEW = "new"
    DUPLICATE = "duplicate"
    NEWER_REVISION = "newer_revision"
    STALE_REVISION = "stale_revision"
    REVISION_CONFLICT = "revision_conflict"


@dataclass(frozen=True, slots=True)
class ProcessedLedgerRecord:
    """Latest successfully accepted version for one logical source event."""

    deduplication_key: str
    source_content_fingerprint: str
    source_revision_at: datetime | None
    canonical_event_id: UUID
    event_type: EventType
    source_provider: str
    source_event_id: str
    event_time: datetime
    schema_version: str

    def __post_init__(self) -> None:
        _validate_non_empty("deduplication_key", self.deduplication_key)
        _validate_fingerprint(self.source_content_fingerprint)
        _validate_non_empty("source_provider", self.source_provider)
        _validate_non_empty("source_event_id", self.source_event_id)
        _validate_non_empty("schema_version", self.schema_version)
        if self.source_revision_at is not None:
            object.__setattr__(
                self,
                "source_revision_at",
                _normalize_utc(self.source_revision_at, "source_revision_at"),
            )
        object.__setattr__(self, "event_time", _normalize_utc(self.event_time, "event_time"))


@dataclass(frozen=True, slots=True)
class ProcessingResolutionResult:
    """Result of ledger-aware processing assessment or successful-state mutation."""

    resolution: ProcessingResolution
    deduplication_key: str
    source_content_fingerprint: str
    previous_source_content_fingerprint: str | None = None
    incoming_source_revision_at: datetime | None = None
    previous_source_revision_at: datetime | None = None


class ProcessingLedger(Protocol):
    """Persistent processing-ledger boundary used by processing semantics."""

    def assess(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        """Return a read-only ledger-aware assessment for one event."""

    def record_success(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        """Record an event version after downstream processing succeeds."""

    def get_record(self, deduplication_key: str) -> ProcessedLedgerRecord | None:
        """Return the latest accepted state for one logical event."""

    def close(self) -> None:
        """Close owned resources."""


class SqliteProcessingLedger:
    """SQLite-backed local implementation of the processing ledger."""

    def __init__(self, path: str | Path) -> None:
        self._path = Path(path)
        self._connection = sqlite3.connect(self._path)
        self._connection.row_factory = sqlite3.Row
        try:
            self._initialize_or_validate_schema()
        except Exception:
            self._connection.close()
            raise

    def assess(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        """Return a read-only processing resolution without mutating the database."""

        incoming = _ledger_record_from_event(event)
        previous = self.get_record(incoming.deduplication_key)
        assessment = _stage_10a_assessment(event=event, previous=previous)
        return _resolve(
            incoming=incoming,
            previous=previous,
            stage_10a_decision=assessment.decision,
        )

    def record_success(self, event: CanonicalEvent) -> ProcessingResolutionResult:
        """Atomically record the latest successfully processed event version."""

        incoming = _ledger_record_from_event(event)
        try:
            self._connection.execute("BEGIN IMMEDIATE")
            previous = self._get_record(incoming.deduplication_key)
            assessment = _stage_10a_assessment(event=event, previous=previous)
            result = _resolve(
                incoming=incoming,
                previous=previous,
                stage_10a_decision=assessment.decision,
            )
            if result.resolution is ProcessingResolution.NEW:
                self._insert_record(incoming)
            elif result.resolution is ProcessingResolution.NEWER_REVISION:
                self._update_record(incoming)
            self._connection.commit()
        except Exception:
            self._connection.rollback()
            raise
        return result

    def get_record(self, deduplication_key: str) -> ProcessedLedgerRecord | None:
        """Return the latest accepted state for a logical event key."""

        return self._get_record(deduplication_key)

    def close(self) -> None:
        """Close the owned SQLite connection."""

        self._connection.close()

    def __enter__(self) -> SqliteProcessingLedger:
        return self

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> None:
        self.close()

    def _initialize_or_validate_schema(self) -> None:
        version = self._read_schema_version()
        if version == 0:
            self._connection.execute(
                """
                CREATE TABLE IF NOT EXISTS processed_events (
                    deduplication_key TEXT PRIMARY KEY NOT NULL,
                    source_content_fingerprint TEXT NOT NULL,
                    source_revision_at TEXT,
                    canonical_event_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    source_provider TEXT NOT NULL,
                    source_event_id TEXT NOT NULL,
                    event_time TEXT NOT NULL,
                    schema_version TEXT NOT NULL
                )
                """
            )
            self._connection.execute(f"PRAGMA user_version = {SQLITE_LEDGER_SCHEMA_VERSION}")
            self._connection.commit()
            return
        if version != SQLITE_LEDGER_SCHEMA_VERSION:
            raise ProcessingConsistencyError("unsupported processing ledger schema version")

    def _read_schema_version(self) -> int:
        row = self._connection.execute("PRAGMA user_version").fetchone()
        return int(row[0])

    def _get_record(self, deduplication_key: str) -> ProcessedLedgerRecord | None:
        _validate_non_empty("deduplication_key", deduplication_key)
        row = self._connection.execute(
            """
            SELECT
                deduplication_key,
                source_content_fingerprint,
                source_revision_at,
                canonical_event_id,
                event_type,
                source_provider,
                source_event_id,
                event_time,
                schema_version
            FROM processed_events
            WHERE deduplication_key = ?
            """,
            (deduplication_key,),
        ).fetchone()
        if row is None:
            return None
        return _record_from_row(row)

    def _insert_record(self, record: ProcessedLedgerRecord) -> None:
        self._connection.execute(
            """
            INSERT INTO processed_events (
                deduplication_key,
                source_content_fingerprint,
                source_revision_at,
                canonical_event_id,
                event_type,
                source_provider,
                source_event_id,
                event_time,
                schema_version
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            _record_parameters(record),
        )

    def _update_record(self, record: ProcessedLedgerRecord) -> None:
        self._connection.execute(
            """
            UPDATE processed_events
            SET
                source_content_fingerprint = ?,
                source_revision_at = ?,
                canonical_event_id = ?,
                event_type = ?,
                source_provider = ?,
                source_event_id = ?,
                event_time = ?,
                schema_version = ?
            WHERE deduplication_key = ?
            """,
            (
                record.source_content_fingerprint,
                _format_optional_timestamp(record.source_revision_at),
                str(record.canonical_event_id),
                record.event_type.value,
                record.source_provider,
                record.source_event_id,
                _format_timestamp(record.event_time),
                record.schema_version,
                record.deduplication_key,
            ),
        )


def _ledger_record_from_event(event: CanonicalEvent) -> ProcessedLedgerRecord:
    assess_event(event, None)
    revision = extract_source_revision(event)
    return ProcessedLedgerRecord(
        deduplication_key=event.metadata.deduplication_key,
        source_content_fingerprint=generate_source_content_fingerprint(event),
        source_revision_at=None if revision is None else revision.source_revision_at,
        canonical_event_id=event.event_id,
        event_type=event.event_type,
        source_provider=event.source.provider,
        source_event_id=event.source.source_event_id,
        event_time=event.event_time,
        schema_version=event.schema_version,
    )


def _resolve(
    *,
    incoming: ProcessedLedgerRecord,
    previous: ProcessedLedgerRecord | None,
    stage_10a_decision: ProcessingDecision,
) -> ProcessingResolutionResult:
    if previous is None:
        if stage_10a_decision is not ProcessingDecision.NEW:
            raise ProcessingConsistencyError("Stage 10A assessment is inconsistent")
        return _resolution_result(ProcessingResolution.NEW, incoming, None)

    if stage_10a_decision is ProcessingDecision.DUPLICATE:
        return _resolution_result(ProcessingResolution.DUPLICATE, incoming, previous)
    if stage_10a_decision is not ProcessingDecision.REVISION_CANDIDATE:
        raise ProcessingConsistencyError("Stage 10A assessment is inconsistent")
    return _resolve_revision_candidate(incoming=incoming, previous=previous)


def _stage_10a_assessment(
    *,
    event: CanonicalEvent,
    previous: ProcessedLedgerRecord | None,
) -> ProcessingAssessment:
    previous_record = None
    if previous is not None:
        previous_record = ProcessedEventRecord(
            deduplication_key=previous.deduplication_key,
            source_content_fingerprint=previous.source_content_fingerprint,
        )
    return assess_event(event, previous_record)


def _resolve_revision_candidate(
    *,
    incoming: ProcessedLedgerRecord,
    previous: ProcessedLedgerRecord,
) -> ProcessingResolutionResult:
    incoming_revision = _source_revision(incoming.source_revision_at)
    previous_revision = _source_revision(previous.source_revision_at)
    if incoming_revision is None or previous_revision is None:
        return _resolution_result(ProcessingResolution.REVISION_CONFLICT, incoming, previous)
    if incoming_revision.source_revision_at > previous_revision.source_revision_at:
        return _resolution_result(ProcessingResolution.NEWER_REVISION, incoming, previous)
    if incoming_revision.source_revision_at < previous_revision.source_revision_at:
        return _resolution_result(ProcessingResolution.STALE_REVISION, incoming, previous)
    return _resolution_result(ProcessingResolution.REVISION_CONFLICT, incoming, previous)


def _resolution_result(
    resolution: ProcessingResolution,
    incoming: ProcessedLedgerRecord,
    previous: ProcessedLedgerRecord | None,
) -> ProcessingResolutionResult:
    return ProcessingResolutionResult(
        resolution=resolution,
        deduplication_key=incoming.deduplication_key,
        source_content_fingerprint=incoming.source_content_fingerprint,
        previous_source_content_fingerprint=(
            None if previous is None else previous.source_content_fingerprint
        ),
        incoming_source_revision_at=incoming.source_revision_at,
        previous_source_revision_at=None if previous is None else previous.source_revision_at,
    )


def _record_parameters(
    record: ProcessedLedgerRecord,
) -> tuple[str, str, str | None, str, str, str, str, str, str]:
    return (
        record.deduplication_key,
        record.source_content_fingerprint,
        _format_optional_timestamp(record.source_revision_at),
        str(record.canonical_event_id),
        record.event_type.value,
        record.source_provider,
        record.source_event_id,
        _format_timestamp(record.event_time),
        record.schema_version,
    )


def _record_from_row(row: sqlite3.Row) -> ProcessedLedgerRecord:
    source_revision_at = row["source_revision_at"]
    return ProcessedLedgerRecord(
        deduplication_key=str(row["deduplication_key"]),
        source_content_fingerprint=str(row["source_content_fingerprint"]),
        source_revision_at=(
            None if source_revision_at is None else _parse_timestamp(str(source_revision_at))
        ),
        canonical_event_id=UUID(str(row["canonical_event_id"])),
        event_type=EventType(str(row["event_type"])),
        source_provider=str(row["source_provider"]),
        source_event_id=str(row["source_event_id"]),
        event_time=_parse_timestamp(str(row["event_time"])),
        schema_version=str(row["schema_version"]),
    )


def _source_revision(value: datetime | None) -> SourceRevision | None:
    if value is None:
        return None
    return SourceRevision(source_revision_at=value)


def _format_optional_timestamp(value: datetime | None) -> str | None:
    if value is None:
        return None
    return _format_timestamp(value)


def _format_timestamp(value: datetime) -> str:
    return _normalize_utc(value, "timestamp").isoformat().replace("+00:00", "Z")


def _parse_timestamp(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    return _normalize_utc(parsed, "timestamp")


def _normalize_utc(value: datetime, field_name: str) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ProcessingConsistencyError(f"{field_name} must be timezone-aware")
    return value.astimezone(UTC)


def _validate_non_empty(field_name: str, value: str) -> None:
    if not value.strip():
        raise ProcessingConsistencyError(f"{field_name} must not be blank")


def _validate_fingerprint(value: str) -> None:
    if _FINGERPRINT_PATTERN.fullmatch(value) is None:
        raise ProcessingConsistencyError("source content fingerprint is malformed")
