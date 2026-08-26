"""Deterministic source-content fingerprints for Canonical Events."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime

from supplychain.contracts import CanonicalEvent

SOURCE_CONTENT_FINGERPRINT_ALGORITHM = "sha256"


def generate_source_content_fingerprint(event: CanonicalEvent) -> str:
    """Return the deterministic source-content fingerprint for one event.

    Inputs are event type, source provider, source event ID, event time, and
    canonical payload. Transport, workflow, enrichment, and producer fields are
    intentionally excluded.
    """

    source_content = {
        "event_time": _canonical_utc_timestamp(event.event_time),
        "event_type": event.event_type.value,
        "payload": event.payload,
        "source": {
            "provider": event.source.provider,
            "source_event_id": event.source.source_event_id,
        },
    }
    canonical_content = json.dumps(
        source_content,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")
    digest = hashlib.sha256(canonical_content).hexdigest()
    return f"{SOURCE_CONTENT_FINGERPRINT_ALGORITHM}:{digest}"


def _canonical_utc_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("event_time must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
