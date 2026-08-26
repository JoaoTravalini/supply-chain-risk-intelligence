# Processing Idempotency Semantics

Stage 10A defines deterministic, side-effect-free identity and fingerprint
semantics for Canonical Events after they are pulled and validated from the
messaging boundary. Stage 10B adds a local persistent processing ledger that can
resolve revision candidates where a supported source revision marker exists.
Neither stage acknowledges Pub/Sub messages, requests redelivery, retries
processing, writes BigQuery rows, or runs a worker coordinator.

## Logical Identity

`deduplication_key` answers:

```text
Which logical source event does this Canonical Event represent?
```

It is produced by the Canonical Event contract from stable source identity
inputs: event type, source provider, source event ID, and event time normalized to
UTC. It deliberately excludes event instance identity, ingestion time, workflow
lineage, enrichment, location context, and payload content.

`event_id` is not an idempotency key. It identifies one Canonical Event instance,
and two canonicalizations of the same logical source event can legitimately have
different `event_id` values.

Pub/Sub `message_id` is not an idempotency key. It is a transport-assigned
message identity and can differ across publishes, redeliveries, emulator runs, or
future cloud deliveries. Transport redelivery is normal under at-least-once
messaging and must not be confused with source-level business identity.

## Source Content Fingerprint

`source_content_fingerprint` answers:

```text
What canonical source content is represented for that logical event?
```

The fingerprint uses exactly these inputs:

- `event_type`;
- `source.provider`;
- `source.source_event_id`;
- `event_time` normalized to one UTC representation;
- canonical `payload`.

The fingerprint excludes:

- Canonical `event_id`;
- `ingested_at`;
- source `request_id`;
- `metadata.correlation_id`;
- `entity`;
- Canonical `location`;
- `metadata.producer`;
- `metadata.producer_version`;
- `metadata.deduplication_key`;
- Pub/Sub `message_id`;
- Pub/Sub `ack_id`.

Payload content is serialized as deterministic JSON using sorted object keys,
compact separators, and UTF-8 bytes before SHA-256 hashing. Nested object key
ordering does not affect the fingerprint. JSON array order remains meaningful, so
changing array order changes the fingerprint.

The current fingerprint format is:

```text
sha256:<lowercase-hex-digest>
```

## Exact Duplicate Candidate

Same `deduplication_key` plus same `source_content_fingerprint` means the same
logical source event with the same source content.

This is an exact application duplicate candidate. It does not prove that the
Pub/Sub transport message, `message_id`, `ack_id`, `event_id`, ingestion time, or
correlation lineage are identical.

Conceptual example:

```text
first delivery:
  event_id = 11111111-1111-4111-8111-111111111111
  message_id = transport-a
  deduplication_key = logical-abc
  source_content_fingerprint = sha256:aaa...

redelivery or recanonicalization:
  event_id = 22222222-2222-4222-8222-222222222222
  message_id = transport-b
  deduplication_key = logical-abc
  source_content_fingerprint = sha256:aaa...

assessment:
  DUPLICATE
```

## Revision Candidate

Same `deduplication_key` plus different `source_content_fingerprint` means the
same logical source event appears with changed source content.

Stage 10A classifies this only as `REVISION_CANDIDATE`. Stage 10B then resolves
the candidate through the persistent ledger when the provider exposes a usable
revision signal, such as USGS `source_updated_at`.

The Stage 10B progression is:

```text
REVISION_CANDIDATE
-> revision-aware ledger resolution
-> NEWER_REVISION | STALE_REVISION | REVISION_CONFLICT
```

Stage 10B does not decide transport ACK/NACK behavior. Stage 10C will map
processing outcomes and downstream success or failure to ACK/NACK policy.

Conceptual example:

```text
USGS feature id = us7000abcd
event_time = 2026-08-25T20:00:00Z
deduplication_key = logical-earthquake-abc

payload version A:
  magnitude = 4.6
  source_updated_at = 2026-08-25T21:00:00Z
  source_content_fingerprint = sha256:aaa...

payload version B:
  magnitude = 5.1
  source_updated_at = 2026-08-25T22:00:00Z
  source_content_fingerprint = sha256:bbb...

assessment:
  REVISION_CANDIDATE
```

## Decision Taxonomy

Stage 10A defines exactly three processing decisions:

- `NEW`: no previous record was supplied for the logical event.
- `DUPLICATE`: the previous record has the same logical identity and the same
  source content fingerprint.
- `REVISION_CANDIDATE`: the previous record has the same logical identity and a
  different source content fingerprint.

If a caller supplies a previous record with a different `deduplication_key`, the
comparison fails explicitly. The caller should pass no previous record when no
matching logical event exists.

## Stage Boundaries

Stage 10A has no persistence. It is a pure local contract for how processing
identity and source-content equality are represented and calculated.

Stage 10B defines the local persistent idempotency ledger and revision-aware
ordering decisions. The ledger records successful processing state only through
an explicit `record_success` operation.

Stage 10C will define the processing coordinator, ACK/NACK policy, retry policy,
poison-message handling, and DLQ behavior.
