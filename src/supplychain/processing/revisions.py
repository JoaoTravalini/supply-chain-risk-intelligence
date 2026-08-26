"""Contract-aware source revision extraction."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime

from pydantic import ValidationError

from supplychain.contracts import CanonicalEvent, EventType, SeismicEventPayload
from supplychain.processing.decisions import ProcessingConsistencyError


@dataclass(frozen=True, slots=True)
class SourceRevision:
    """Comparable source revision marker approved for Stage 10B."""

    source_revision_at: datetime

    def __post_init__(self) -> None:
        if self.source_revision_at.tzinfo is None or self.source_revision_at.utcoffset() is None:
            raise ProcessingConsistencyError("source revision timestamp must be timezone-aware")
        object.__setattr__(
            self,
            "source_revision_at",
            self.source_revision_at.astimezone(UTC),
        )


def extract_source_revision(event: CanonicalEvent) -> SourceRevision | None:
    """Extract a comparable source revision marker when an approved contract exists."""

    if event.source.provider == "usgs" and event.event_type is EventType.SEISMIC_EVENT_DETECTED:
        try:
            payload = SeismicEventPayload.model_validate_json(json.dumps(event.payload))
        except ValidationError as exc:
            raise ProcessingConsistencyError(
                "USGS seismic event payload does not match the revision contract"
            ) from exc
        return SourceRevision(source_revision_at=payload.source_updated_at)
    return None
