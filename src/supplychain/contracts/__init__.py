"""Public contract models for SupplyChain Sentinel."""

from supplychain.contracts.events import (
    CANONICAL_EVENT_SCHEMA_VERSION,
    CanonicalEvent,
    EntityReference,
    EventMetadata,
    EventType,
    LocationMetadata,
    SourceMetadata,
    generate_deduplication_key,
)
from supplychain.contracts.weather import WeatherObservationPayload

__all__ = [
    "CANONICAL_EVENT_SCHEMA_VERSION",
    "CanonicalEvent",
    "EntityReference",
    "EventMetadata",
    "EventType",
    "LocationMetadata",
    "SourceMetadata",
    "WeatherObservationPayload",
    "generate_deduplication_key",
]
