# Processing Ledger

Stage 10B introduces the persistent processing ledger for successful Canonical
Event processing state.

The ledger is an idempotency and revision index. It is not RAW storage, not an
analytical warehouse table, not a Pub/Sub receipt log, and not a full event
store.

## Purpose

The ledger records the latest successfully accepted source version for each
logical source event after downstream processing has succeeded.

It does not mean a Pub/Sub message was received. A pulled message must not become
ledger state merely because transport delivery happened.

The intended future flow remains:

```text
pull
-> ledger assessment
-> downstream processing
-> downstream success
-> ledger record_success
-> ACK
```

Stage 10B implements only the ledger assessment and successful-state mutation.
The processing coordinator, ACK/NACK policy, retry policy, poison-message
handling, and DLQ behavior remain deferred to Stage 10C.

## Architecture Boundary

Processing code depends on a small `ProcessingLedger` abstraction.

The local implementation is `SqliteProcessingLedger`, backed by Python's
standard-library `sqlite3` module.

```text
processing semantics
-> ProcessingLedger abstraction
-> SQLite local implementation
```

SQLite is the Stage 10B local implementation. It is not claimed as the final
production persistence technology. A later managed transactional implementation
can replace the local adapter without rewriting the processing decision
semantics.

## Logical Key

The ledger primary key is `deduplication_key`.

One `processed_events` row represents the latest successfully accepted source
version for one logical source event.

The ledger does not use Canonical `event_id`, Pub/Sub `message_id`, Pub/Sub
`ack_id`, or source-content fingerprint alone as the primary logical key.

## Stored Metadata

Schema version 1 stores:

- `deduplication_key`;
- `source_content_fingerprint`;
- nullable `source_revision_at`;
- `canonical_event_id`;
- `event_type`;
- `source_provider`;
- `source_event_id`;
- `event_time`;
- `schema_version`.

Timestamps are persisted as explicit UTC strings and reconstructed as
timezone-aware UTC datetimes.

The ledger does not store:

- Pub/Sub `message_id`;
- Pub/Sub `ack_id`;
- full Canonical Event body;
- full payload JSON;
- correlation ID;
- source request ID;
- arbitrary message attributes;
- retry counters;
- DLQ state.

Full event provenance belongs in future RAW storage. The ledger stores only the
safe idempotency/revision metadata needed to decide whether a logical source
event version has already succeeded.

## SQLite Schema Version

The local SQLite ledger uses `PRAGMA user_version`.

Stage 10B schema version is `1`.

Behavior:

- `user_version = 0`: initialize the `processed_events` table and set version 1.
- `user_version = 1`: open normally.
- unsupported newer or unknown versions: fail explicitly.

No migration framework is implemented in Stage 10B.

## assess vs record_success

`assess(event)` is read-only. It computes the incoming source-content
fingerprint, reads the current persisted row by `deduplication_key`, and returns a
ledger-aware resolution. It does not insert or update any row.

`record_success(event)` is the explicit mutation. It means downstream processing
for this event version has already succeeded and the ledger may record that
successful version.

`record_success(event)` re-reads the latest row inside an SQLite transaction
before deciding whether to insert, update, or leave state unchanged.

## Revision Extraction

Revision extraction is explicit and contract-aware.

The only supported source revision marker in Stage 10B is:

```text
source.provider == "usgs"
event_type == "seismic.event.detected"
payload validates as SeismicEventPayload
SeismicEventPayload.source_updated_at
```

No generic payload field search is performed. Other current providers and event
types have no comparable revision marker.

The ledger does not infer revision ordering from `ingested_at`, `event_id`,
producer version, request ID, Pub/Sub timestamps, or arrival order.

## Resolution Taxonomy

`NEW`: no ledger row exists for the event's `deduplication_key`.

`DUPLICATE`: a row exists with the same `deduplication_key` and the same
`source_content_fingerprint`.

`NEWER_REVISION`: a row exists with the same `deduplication_key`, different
source content, and both previous and incoming source revision timestamps exist
with incoming greater than previous.

`STALE_REVISION`: a row exists with the same `deduplication_key`, different
source content, and both revision timestamps exist with incoming less than
previous.

`REVISION_CONFLICT`: a row exists with the same `deduplication_key`, different
source content, and ordering cannot safely prove the incoming content is newer.
This includes equal source revision timestamps with different fingerprints, and
cases where either side has no comparable revision marker.

## Out-of-Order Protection

`record_success(event)` uses an SQLite `BEGIN IMMEDIATE` transaction and re-reads
the latest row before writing.

This protects the persisted ledger state from simple local races and
out-of-order successful writes. A stale source revision cannot overwrite a newer
accepted revision, and an exact duplicate is idempotent.

The ledger does not create a distributed exactly-once transaction across future
external side effects, BigQuery writes, or Pub/Sub acknowledgement. That broader
coordination belongs to Stage 10C and later persistence architecture.
