"""Deterministic BigQuery row mappers for validated domain contracts."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime

from pydantic import JsonValue

from supplychain.contracts import CanonicalEvent
from supplychain.domain import Supplier
from supplychain.processing.fingerprints import generate_source_content_fingerprint
from supplychain.processing.revisions import extract_source_revision

type BigQueryScalar = str | int | float | bool | None
type BigQueryValue = BigQueryScalar | JsonValue
type BigQueryRow = dict[str, BigQueryValue]


def canonical_event_to_raw_row(event: CanonicalEvent) -> BigQueryRow:
    """Map one validated Canonical Event to the RAW canonical_events row shape."""

    revision = extract_source_revision(event)
    return {
        "event_id": str(event.event_id),
        "event_type": event.event_type.value,
        "schema_version": event.schema_version,
        "event_time": _format_timestamp(event.event_time),
        "ingested_at": _format_timestamp(event.ingested_at),
        "source_provider": event.source.provider,
        "source_endpoint": event.source.endpoint,
        "source_event_id": event.source.source_event_id,
        "source_request_id": event.source.request_id,
        "entity_type": None if event.entity is None else event.entity.type,
        "entity_id": None if event.entity is None else event.entity.id,
        "location_country_code": None if event.location is None else event.location.country_code,
        "location_region": None if event.location is None else event.location.region,
        "correlation_id": event.metadata.correlation_id,
        "producer": event.metadata.producer,
        "producer_version": event.metadata.producer_version,
        "deduplication_key": event.metadata.deduplication_key,
        "source_content_fingerprint": generate_source_content_fingerprint(event),
        "source_revision_at": (
            None if revision is None else _format_timestamp(revision.source_revision_at)
        ),
        "payload": dict(event.payload),
    }


def supplier_to_core_row(supplier: Supplier) -> BigQueryRow:
    """Map one validated Supplier v1 object to the CORE suppliers row shape."""

    return {
        "schema_version": supplier.schema_version,
        "supplier_id": supplier.supplier_id,
        "name": supplier.name,
        "category": supplier.category.value,
        "criticality": supplier.criticality.value,
        "country_code": supplier.location.country_code,
        "region": supplier.location.region,
        "city": supplier.location.city,
        "latitude": supplier.location.latitude,
        "longitude": supplier.location.longitude,
        "annual_spend_usd": supplier.annual_spend_usd,
        "typical_lead_time_days": supplier.typical_lead_time_days,
        "dependency_score": supplier.dependency_score,
        "single_source": supplier.single_source,
    }


def rows_as_mappings(rows: tuple[BigQueryRow, ...]) -> tuple[Mapping[str, BigQueryValue], ...]:
    """Return rows as immutable sequence of mappings for client protocol typing."""

    return rows


def _format_timestamp(value: datetime) -> str:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("BigQuery timestamp values must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")
