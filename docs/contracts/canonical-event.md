# Canonical Event Contract

The canonical event contract defines the validated envelope used at the platform's event-driven boundary. External source records are expected to be normalized by a future adapter into Canonical Event v1 before messaging and before RAW analytical storage.

Stage 6 defines only the envelope contract, validation behavior, deterministic logical deduplication key, and JSON Schema artifact. It does not implement Pub/Sub, adapters, RAW tables, source-specific payload schemas, or transformations.

## Envelope Structure

Canonical Event v1 contains:

- `event_id`: unique UUID identity for this canonical event instance.
- `event_type`: approved event type enum value.
- `schema_version`: canonical event schema version, currently `1.0.0`.
- `event_time`: source or business timestamp for when the represented event occurred.
- `ingested_at`: UTC timestamp for when the event entered or was canonicalized by the platform.
- `source`: source provenance metadata.
- `entity`: optional platform entity reference when correlation already exists.
- `location`: optional minimal location context.
- `payload`: JSON-object-compatible event-specific content.
- `metadata`: canonicalization and processing metadata.

The envelope and nested metadata models reject unknown fields and are immutable after validation.

## Event Types

Stage 6 approves exactly these event types:

- `weather.observation.recorded`
- `seismic.event.detected`
- `supplier.operational.snapshot.recorded`

Unknown event types fail validation. Additional event types require an explicit future contract update.

## Schema Versioning

The initial schema version is `1.0.0`.

Version evolution follows semantic-version intent:

- PATCH: compatible clarification or non-breaking correction.
- MINOR: backward-compatible addition.
- MAJOR: breaking contract change.

Multi-version dispatch is intentionally deferred.

## Time Semantics

`event_time` is the timestamp at which the represented event occurred according to the source or business domain.

`ingested_at` is the timestamp at which the event entered or was canonicalized within SupplyChain Sentinel.

Both timestamps must be timezone-aware. Naive datetimes are rejected. Aware non-UTC timestamps are normalized to UTC; the platform does not guess a timezone.

## Identity Semantics

### Event Instance Identity

`event_id` is a UUID for one canonical event instance or delivery. Two independent canonicalizations of the same source event may have different `event_id` values.

### Source Event Identity

The stable source event identity is `source.provider` plus `source.source_event_id`.

If the upstream source provides a stable event or record identifier, a future source adapter must use that identifier. If the upstream source does not provide one, the source-specific adapter must derive a deterministic `source_event_id` from that source's stable natural key before constructing the Canonical Event.

Possible future natural-key ingredients may include provider-specific observation time, geographic coordinates, source record type, or other source-specific stable dimensions. The generic Canonical Event layer does not guess provider natural keys and does not implement adapter-specific identity algorithms.

### Logical Deduplication Identity

The logical deduplication identity is:

- source provider;
- event type;
- source event ID;
- event time normalized to UTC.

### Workflow Lineage

`correlation_id` represents workflow or request lineage across multiple operations or events. It is not the same as `event_id` and is not the logical deduplication key. Distributed tracing is deferred.

## Source Provenance

Source metadata records:

- `provider`: required source/provider identifier.
- `endpoint`: optional endpoint or source reference.
- `source_event_id`: required stable event or record identity within the source/provider namespace.
- `request_id`: optional request identifier for source retrieval.

Source metadata must never contain credentials, API keys, access tokens, secret query parameters, or sensitive account identifiers.

## Entity And Location

`entity` is optional because external events can exist before supplier or platform-entity correlation. When supplied, it contains a generic `type` and `id`; the envelope does not hardcode supplier-only behavior.

Entity correlation does not participate in logical source event identity. An event can initially exist without a supplier association and later be enriched with an entity such as `SUP-0042`; that enrichment must not redefine which external event it represents.

`location` is optional. When supplied, `country_code` must use uppercase two-letter ISO-like syntax. `region` is a minimal free-text regional reference. Stage 6 does not introduce geospatial modeling.

## Deterministic Deduplication Key

The logical deduplication key is a SHA-256 hash generated from stable logical identity inputs:

- source provider;
- event type;
- source event ID;
- event time normalized to UTC.

The key deliberately excludes delivery, workflow, enrichment, content, and context values:

- `event_id`;
- `ingested_at`;
- source request ID;
- `correlation_id`.
- `entity`;
- `location`;
- `payload`.

`entity` is excluded because it may be assigned or changed through enrichment/correlation. `location` and `payload` are excluded because they are event content or context and may receive representational, non-identity changes.

Inputs are serialized as canonical JSON with sorted keys before hashing so incidental Python dictionary ordering cannot change the result. The key is deterministic only for exact logical identity; fuzzy deduplication is not implemented.

## Payload Strategy

`payload` is event-specific source or business content. Stage 6 restricts it to a JSON-compatible object while deferring weather, seismic, and operational payload schemas. Source-specific payload schemas will be defined when their ingestion stages arrive.

## Security

Contract metadata and examples must never contain secrets, credentials, API keys, bearer tokens, service-account keys, developer account emails, billing identifiers, or sensitive source endpoint parameters.

## Example

```json
{
  "event_id": "5f3b719c-0b5f-4c8c-9c92-0d2f3d0b9f10",
  "event_type": "weather.observation.recorded",
  "schema_version": "1.0.0",
  "event_time": "2026-08-25T12:00:00Z",
  "ingested_at": "2026-08-25T12:01:00Z",
  "source": {
    "provider": "synthetic-weather",
    "endpoint": "observations/daily",
    "source_event_id": "weather-obs-001",
    "request_id": "request-001"
  },
  "entity": {
    "type": "supplier",
    "id": "supplier-001"
  },
  "location": {
    "country_code": "US",
    "region": "WA"
  },
  "payload": {
    "temperature_c": 21.2,
    "observed": true
  },
  "metadata": {
    "correlation_id": "corr-001",
    "producer": "canonicalizer",
    "producer_version": "1.2.3",
    "deduplication_key": "f5d85d3f19a0b6ea6a743be820f9e22425d8580212604352554e2968c7d5e47d"
  }
}
```
