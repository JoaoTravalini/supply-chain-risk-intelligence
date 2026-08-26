"""Canonical event contract for the event-driven platform boundary."""

from __future__ import annotations

import hashlib
import json
import re
from datetime import UTC, datetime
from enum import StrEnum
from typing import Annotated, Literal
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, JsonValue, StringConstraints, field_validator

CANONICAL_EVENT_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]
Identifier = Annotated[
    str,
    StringConstraints(
        strip_whitespace=True,
        min_length=1,
        pattern=r"^[A-Za-z0-9][A-Za-z0-9._:/@-]*$",
        strict=True,
    ),
]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$", strict=True)]
SemanticVersion = Annotated[
    str,
    StringConstraints(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$",
        strict=True,
    ),
]


class StrictContractModel(BaseModel):
    """Base for immutable, strict contract models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class EventType(StrEnum):
    """Approved canonical event types for schema version 1.0.0."""

    WEATHER_OBSERVATION_RECORDED = "weather.observation.recorded"
    SEISMIC_EVENT_DETECTED = "seismic.event.detected"
    SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED = "supplier.operational.snapshot.recorded"


class SourceMetadata(StrictContractModel):
    """Source provenance metadata without credentials or secrets."""

    provider: NonEmptyString
    source_event_id: NonEmptyString
    endpoint: NonEmptyString | None = None
    request_id: Identifier | None = None


class EntityReference(StrictContractModel):
    """Reference to a platform entity associated with an event."""

    type: Identifier
    id: Identifier


class LocationMetadata(StrictContractModel):
    """Minimal location metadata for event context."""

    country_code: CountryCode | None = None
    region: NonEmptyString | None = None

    @field_validator("region")
    @classmethod
    def normalize_region(cls, value: str | None) -> str | None:
        if value is None:
            return None
        return value.strip()


class EventMetadata(StrictContractModel):
    """Metadata produced while canonicalizing an event."""

    correlation_id: Identifier
    producer: Identifier
    producer_version: SemanticVersion
    deduplication_key: Identifier


class CanonicalEvent(StrictContractModel):
    """Immutable canonical event envelope for event-driven ingestion."""

    event_id: UUID = Field(default_factory=uuid4)
    event_type: EventType
    schema_version: Literal["1.0.0"] = CANONICAL_EVENT_SCHEMA_VERSION
    event_time: datetime
    ingested_at: datetime = Field(default_factory=lambda: datetime.now(UTC))
    source: SourceMetadata
    entity: EntityReference | None = None
    location: LocationMetadata | None = None
    payload: dict[str, JsonValue]
    metadata: EventMetadata

    @field_validator("event_time", "ingested_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("timestamp must be timezone-aware")
        return value.astimezone(UTC)


def generate_deduplication_key(
    *,
    source: SourceMetadata,
    event_type: EventType,
    event_time: datetime,
) -> str:
    """Generate the stable logical event identity hash.

    Identity inputs are source provider, event type, source event ID, and event
    time. Delivery, workflow, enrichment, location, and payload data are excluded.
    """

    normalized_event_time = _normalize_identity_time(event_time)
    identity = {
        "event_time": normalized_event_time.isoformat().replace("+00:00", "Z"),
        "event_type": event_type.value,
        "source_event_id": source.source_event_id,
        "source_provider": source.provider,
    }
    canonical_identity = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()


def _normalize_identity_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("event_time must be timezone-aware")
    return value.astimezone(UTC)


assert re.fullmatch(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$",
    CANONICAL_EVENT_SCHEMA_VERSION,
)
