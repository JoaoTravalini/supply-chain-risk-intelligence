"""Canonical Event serialization and Pub/Sub attribute derivation."""

from __future__ import annotations

import json

from supplychain.contracts import CanonicalEvent

MESSAGE_CONTENT_TYPE = "application/json"


def serialize_canonical_event(event: CanonicalEvent) -> bytes:
    """Serialize a Canonical Event envelope as deterministic UTF-8 JSON bytes."""

    body = event.model_dump(mode="json")
    return json.dumps(
        body,
        ensure_ascii=False,
        separators=(",", ":"),
        sort_keys=True,
    ).encode("utf-8")


def canonical_event_attributes(event: CanonicalEvent) -> dict[str, str]:
    """Derive safe Pub/Sub attributes from the validated Canonical Event."""

    return {
        "content_type": MESSAGE_CONTENT_TYPE,
        "correlation_id": event.metadata.correlation_id,
        "deduplication_key": event.metadata.deduplication_key,
        "event_id": str(event.event_id),
        "event_type": event.event_type.value,
        "producer": event.metadata.producer,
        "producer_version": event.metadata.producer_version,
        "schema_version": event.schema_version,
        "source_provider": event.source.provider,
    }
