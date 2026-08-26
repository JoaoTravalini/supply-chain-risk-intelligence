"""Canonical Event serialization and Pub/Sub attribute derivation."""

from __future__ import annotations

import json

from pydantic import ValidationError

from supplychain.contracts import CanonicalEvent
from supplychain.messaging.errors import (
    MessageAttributeMismatchError,
    MessageDeserializationError,
)

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


def deserialize_canonical_event(data: bytes) -> CanonicalEvent:
    """Deserialize UTF-8 JSON bytes into a validated Canonical Event."""

    try:
        text = data.decode("utf-8")
        json.loads(text)
        return CanonicalEvent.model_validate_json(text)
    except (UnicodeDecodeError, json.JSONDecodeError, ValidationError) as exc:
        raise MessageDeserializationError("Message data is not a valid Canonical Event") from exc


def validate_canonical_event_attributes(
    *,
    event: CanonicalEvent,
    attributes: dict[str, str],
    message_id: str | None = None,
) -> None:
    """Validate standard Pub/Sub attributes against the authoritative event body."""

    expected = canonical_event_attributes(event)
    for key, expected_value in expected.items():
        actual_value = attributes.get(key)
        if actual_value != expected_value:
            raise MessageAttributeMismatchError(
                "Pub/Sub message attribute does not match Canonical Event body",
                attribute=key,
                message_id=message_id,
            )
