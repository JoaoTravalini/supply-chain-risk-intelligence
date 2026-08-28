# BigQuery RAW/CORE Pipeline

Stage 11 defines the Sandbox-compatible BigQuery data pipeline for canonical
events and Supplier master data.

## Sandbox Constraints

The development project uses BigQuery Sandbox without billing. The working
Stage 11 architecture must therefore avoid unsupported paths:

- no streaming inserts;
- no Storage Write API path;
- no DML `INSERT`, `UPDATE`, `DELETE`, or `MERGE`;
- no Python read-modify-write substitute for `MERGE`.

Warehouse writes use BigQuery batch load jobs. This keeps development
compatible with the current no-billing environment.

## RAW Canonical Events

`supplychain_raw.canonical_events` is the append-oriented Canonical Event v1
source-version history table.

It represents canonical event versions that reach the approved warehouse
handler. It is not a Pub/Sub transport-delivery log and does not attempt to
persist every redelivery, `ack_id`, delivery attempt, retry counter, or DLQ
state.

RAW preserves:

- Canonical Event identity, type, schema version, event time, and ingestion
  time;
- source provenance;
- optional entity and location context;
- correlation and producer metadata;
- logical `deduplication_key`;
- deterministic `source_content_fingerprint`;
- nullable `source_revision_at` where the source contract explicitly supports
  revision comparison;
- canonical source-specific payload as native BigQuery `JSON`.

The table is partitioned by `ingested_at` at day granularity because RAW
physical organization represents warehouse arrival. Late or replayed source
events may have old `event_time`, so `event_time` is not the RAW partitioning
authority.

The table clusters by `event_type`, `source_provider`, and `deduplication_key`
to support event-type filtering, provider filtering, and logical event/revision
lookup without over-clustering.

RAW does not enforce uniqueness on `deduplication_key`. Multiple rows may share
the same logical identity because RAW preserves source revisions and possible
replay or reprocessing duplicates.

## Fingerprints And Revisions

The warehouse row mapper reuses the existing
`generate_source_content_fingerprint` implementation. It does not introduce a
second fingerprint algorithm.

`source_revision_at` uses the existing Stage 10B extraction contract:

- USGS seismic Canonical Event -> `SeismicEventPayload.source_updated_at`;
- all other current event/provider combinations -> `NULL`.

The mapper does not inspect arbitrary payload keys named `source_updated_at` and
does not infer revisions from ingestion time, event ID, or producer version.

## CORE Canonical Events

`supplychain_core.canonical_events` is a BigQuery view over
`supplychain_raw.canonical_events`.

The view is the current Sandbox-compatible authoritative query-time current
state for canonical events. It is not a DML-maintained table and has no
independent partitioning or clustering. Future billed/production architecture
may materialize CORE differently if justified.

For unversioned logical events, the view selects a deterministic representative
only after proving all RAW rows for the `deduplication_key` have the same
`source_content_fingerprint`. If unversioned rows have multiple fingerprints,
the logical event is excluded from authoritative current-state output.

For revision-aware logical events, the view selects the greatest
`source_revision_at`. If all rows at that greatest revision have the same
fingerprint, it chooses one deterministic representative by `ingested_at` and
`event_id`. If multiple fingerprints exist at the greatest revision, the
logical event is excluded as a revision conflict.

If a `deduplication_key` contains a mixture of rows with and without
`source_revision_at`, the view treats that as an integrity ambiguity and
excludes the logical event from authoritative current-state output.

The view deliberately avoids blind last-arrival-wins semantics.

## Supplier Master Data

`supplychain_core.suppliers` is a physical BigQuery table for Supplier v1 master
data. Its logical key is `supplier_id`; BigQuery does not enforce a relational
primary key in this development design.

The synthetic Supplier dataset is an authoritative current development snapshot,
so `BigQuerySupplierSnapshotLoader` uses a batch load job with `WRITE_TRUNCATE`.
Future source-of-truth master-data ingestion may use a different incremental
strategy.

The Supplier table is not partitioned or clustered. The current synthetic
portfolio is intentionally small, and unnecessary physical optimization would
add complexity without a demonstrated access pattern.

## Runtime Flow

The per-event processing flow is:

```text
ProcessingCoordinator
-> BigQueryCanonicalEventHandler
-> RAW load job completion
-> handler success
-> ProcessingLedger.record_success
-> ACK
```

The handler appends only the Canonical Event to RAW. Because CORE canonical
events are a view over RAW, there is no per-event CORE DML step.

`BigQueryCanonicalEventHandler` does not ACK Pub/Sub and does not mutate the
ProcessingLedger directly. The existing `ProcessingCoordinator` remains the
owner of safe handler, ledger, and ACK ordering.

For bounded Sandbox/portfolio development, one load job per handled event is
acceptable. It is not the intended high-throughput production batching strategy.
Future worker/runtime stages must introduce proper batching before claiming
production throughput.

## Partial Failure Semantics

The pipeline is not a distributed atomic transaction:

```text
RAW load succeeds
-> later processing step fails
-> handler raises
-> ProcessingLedger is not marked successful
-> Pub/Sub is not ACKed
-> redelivery may append another RAW row
```

Exact duplicate RAW rows are expected in this failure mode. CORE must collapse
safe duplicates and exclude ambiguous conflicts rather than selecting a winner
by arrival time alone.

## ProcessingLedger vs BigQuery

The ProcessingLedger is synchronous operational state for processing
idempotency and revision-aware ACK safety.

BigQuery RAW is analytical canonical version/history storage.

BigQuery CORE is authoritative query-time current canonical state over RAW.

These responsibilities are intentionally separate.

## Future Production Evolution

Deferred work includes human approval of the Stage 11 plan, `tofu apply`,
deployed-resource validation, live Supplier snapshot loading, synthetic
Canonical Event RAW smoke, production batching runtime, production
ProcessingLedger, production Pub/Sub IaC, MART risk models, LangGraph, and
Streamlit.
