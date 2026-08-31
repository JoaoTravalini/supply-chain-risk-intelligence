# Data Architecture

SupplyChain Sentinel uses a layered BigQuery analytical model. Stage 5 provisioned the RAW, CORE, and MART dataset boundaries in BigQuery Sandbox through OpenTofu. Stage 11 deployed the first RAW/CORE physical objects and local warehouse runtime boundary. Stage 12 deploys the deterministic Supplier Risk Model v1 MART current/history tables.

## Analytical Layers

### RAW

RAW preserves ingested source records and source fidelity wherever practical. It retains provenance and ingestion metadata, and supports replay, debugging, and auditing.

RAW is not the preferred user-facing query layer. Consumers should use CORE or MART when the required information has been validated and modeled there.

Stage 11 defines `supplychain_raw.canonical_events` as an append-oriented
Canonical Event v1 source-version history table populated by BigQuery batch load
jobs. RAW is not a Pub/Sub transport-delivery log and does not store `ack_id`,
delivery attempts, retry counters, or DLQ state. Exact duplicate RAW rows are
possible after partial failures or replay and must be tolerated.

### CORE

CORE contains the canonical typed business representation. It is the boundary for normalized, validated, and deduplicated domain-oriented records.

CORE is the preferred source for reusable domain data and agent tools when MART does not yet provide the required analytical model.

Stage 11 defines `supplychain_core.canonical_events` as a BigQuery view over RAW
that exposes authoritative query-time current canonical state. The view
collapses exact duplicates, chooses the greatest comparable source revision
where available, and excludes unversioned, equal-revision, or mixed
revision-marker conflicts instead of using blind last-arrival-wins behavior.

Stage 11 also defines `supplychain_core.suppliers` as the Supplier v1
master-data snapshot table. Its logical key is `supplier_id`.

### MART

MART contains business-facing analytical models. It supports supplier risk analytics, historical risk, factor decomposition, dashboards, and optimized consumption by Streamlit and LangGraph data tools.

MART should not be used as a raw ingestion landing area, and normal application workflows should not write directly to MART.

Stage 12 defines and deploys `supplychain_mart.supplier_risk_current` as the
latest Supplier Risk Model v1 snapshot and
`supplychain_mart.supplier_risk_history` as append-oriented assessment history.
One full 120-Supplier development assessment batch was loaded for validation.
Live environmental factor scores depend on qualifying CORE weather and seismic
evidence.

## Intended Flow

```text
External Sources
      ↓
Adapter
      ↓
Canonical Event v1
      ↓
Messaging
      ↓
RAW
      ↓
Validation / Normalization / Deduplication
      ↓
CORE
      ↓
Business Transformations
      ↓
MART
```

The Canonical Event v1 contract now exists as the platform boundary for future source normalization. The Open-Meteo adapter can canonicalize current-weather observations into Canonical Event v1 in local code, and the USGS adapter can canonicalize bounded nearby earthquake query results into Canonical Event v1. Stage 9 allows Canonical Events to cross the local Pub/Sub messaging boundary through the `canonical-events-v1` topic and return as validated Canonical Events through the `canonical-events-processing-v1` pull subscription. Stage 10C can coordinate one already-valid received Canonical Event through ledger assessment, handler execution, successful ledger mutation, ACK, failure classification, and bounded disposition intent. Stage 11 adds a `BigQueryCanonicalEventHandler` that appends approved events to RAW through a batch load job before handler success returns to the ProcessingCoordinator.

Pub/Sub is transport, not the system of record. ProcessingLedger is synchronous operational idempotency and revision index state used for safe processing and ACK decisions. BigQuery RAW is canonical version/history storage. BigQuery CORE canonical events are authoritative query-time current state over RAW. CORE suppliers are master-data snapshot state. Stage 12 MART contains deterministic supplier risk assessments derived from CORE.

Stage 12 risk progression:

```text
CORE suppliers
+ CORE canonical events
-> deterministic risk engine
-> MART current/history
```

LangGraph will later read and explain MART risk outputs. It does not calculate
authoritative risk scores.

Stage 13 adds PostgreSQL-backed LangGraph checkpoint state for operational
investigation workflow persistence:

```text
InvestigationService
-> LangGraph
-> PostgreSQL checkpoint state
```

This state is not BigQuery analytical data, does not replace RAW/CORE/MART, and
does not replace the ProcessingLedger. Guarded BigQuery agent tools remain
deferred.

Stage 14 adds the guarded normal agent read path over CORE and MART:

```text
Agent Data Service
-> Guarded BigQuery Reader
-> CORE suppliers / CORE canonical_events
-> MART supplier risk current/history
```

Agent-facing reads do not expose RAW. RAW remains the audit, replay, and source
history layer. The agent reads authoritative current risk from MART rather than
recalculating it.

Stage 15 uses that guarded path inside the LangGraph investigation workflow:

```text
InvestigationService
-> LangGraph
-> AgentDataService
-> CORE supplier profile / CORE canonical evidence
-> MART current risk / MART risk history
-> bounded structured context
-> Gemini explanation
-> validated InvestigationReport
-> PostgreSQL checkpoint state
```

The workflow does not read RAW, mutate BigQuery, recalculate risk, or let Gemini
generate SQL. PostgreSQL checkpoints remain operational agent state rather than
analytical warehouse data.

Canonical Events always carry stable source identity through `source.provider` and `source_event_id`. Future source adapters are responsible for deriving deterministic source IDs from provider-specific natural keys when an upstream source does not expose a native stable identifier.

The Supplier master-data contract now defines canonical supplier identity, category, criticality, location, exposure, lead time, dependency, and sourcing concentration. Canonical Supplier master data now exists as a versioned synthetic JSONL artifact validated through the Supplier v1 contract. Stage 11 defines the physical CORE supplier table and batch snapshot loader, but the live load remains deferred until after human approval of the OpenTofu plan and apply checkpoint.

The analytical progression is intentionally one-way. Later stages may define controlled rebuild or replay workflows, but those workflows should preserve the same layer responsibilities.

## Provenance

RAW and subsequent layers must preserve enough lineage to determine, where applicable:

- Source system or provider.
- Source event or reference identity.
- Ingestion timestamp.
- Event or business timestamp.
- Schema or contract version.
- Correlation identifiers.

These are architectural concepts in Stage 5A. Physical columns and models are deferred to later stages.

## Deduplication Boundary

RAW preserves source records and favors append-oriented semantics. CORE is the first analytical layer expected to contain deduplicated canonical records.

Logical idempotency is based only on stable source identity fields, event type, and event time. Later enrichment, including supplier/entity correlation, must not redefine which source event a canonical record represents.

Source-event identity and source revision must remain distinct. For USGS, the stable provider Feature ID identifies the earthquake source event, while `source_updated_at` in the seismic payload identifies the freshness of the provider catalog revision represented by that record. Future RAW should preserve provider revisions, and future CORE processing must not treat a newer provider revision of the same logical earthquake as merely a meaningless at-least-once duplicate.

Stage 10A introduces the source-content fingerprint as a separate deterministic concept from logical `deduplication_key`. Future RAW and CORE processing must preserve the distinction between the same logical source event with identical content and the same logical source event with changed content. Changed content with the same logical identity is a revision candidate, not something to discard blindly as a transport duplicate.

Stage 10B adds a local processing ledger. The ledger is not RAW and is not the analytical warehouse. It stores only idempotency/revision index metadata: logical key, source-content fingerprint, supported source revision marker, and safe event identity metadata. Stage 11 RAW persists full Canonical Event warehouse rows and source payloads separately from the ledger.

The ledger prevents stale accepted revision state from overwriting a newer accepted revision for the same logical event. It is not a BigQuery table and is not used as the analytical source of record.

The ProcessingCoordinator uses the ledger as the gate for safe handler
execution and ACK. The Stage 11 BigQuery handler is a downstream handler that
must complete the RAW load before the coordinator records ledger success and
ACKs. The handler does not ACK or mutate the ledger directly.

MART should consume CORE or other approved modeled data rather than reimplementing raw deduplication logic independently.

## Supplier Master Data

Supplier master data describes relatively stable supplier attributes such as identity, location, category, criticality, annual exposure, lead-time expectation, dependency, and sourcing concentration.

Dynamic operational performance does not belong in the Supplier master contract. Current risk score, delivery metrics, defect rates, weather risk, seismic risk, anomaly score, and current status metrics are deferred to operational observations, transformations, or risk analytics.

## Authoritative and Derived Data

Authoritative supplier risk metrics must come from deterministic, versioned business logic. MART may contain derived analytical outputs for dashboards and agent queries, but those outputs must remain traceable to inputs, rules, and calculation versions when risk scoring is implemented.

The LLM may explain evidence and summarize findings, but it must not define authoritative business metrics.

## Naming Principles

Dataset names are:

- `supplychain_raw`
- `supplychain_core`
- `supplychain_mart`

Future table names should be clear, domain-oriented, lowercase, and consistent within their layer. Stage 5A does not define table names or physical schemas.

## Partitioning and Clustering

Future large or event-oriented tables must deliberately evaluate:

- Event-time or business-date partitioning.
- Mandatory partition filtering where useful.
- Clustering based on actual query access patterns.
- Query bytes and cost behavior.
- Retention requirements.

No single partitioning or clustering strategy applies globally before table access patterns exist. Future physical table designs must justify these choices per table.

## Data Quality

Data quality expectations increase as data moves from RAW to CORE to MART:

- RAW preserves input evidence and ingestion context.
- CORE validates, normalizes, types, and deduplicates.
- MART exposes business-ready analytical models.

Validation failures and rejected records should remain observable when later processing stages are implemented.

## BigQuery Location

The development default location is `US`.

The project currently contains synthetic, non-sensitive portfolio data, and no regulatory data-residency requirement has been identified. The location is still explicit and configurable through infrastructure instead of being scattered across resource definitions.

Future production deployment must review data residency, service co-location, latency, and organizational requirements rather than assuming the development location.

## BigQuery Sandbox Constraints

The current development phase runs without a Cloud Billing Account. BigQuery Sandbox provides limited no-billing functionality.

Current billing-free development must account for:

- Limited free storage and query usage.
- Automatic sandbox expiration behavior: development datasets explicitly represent the Sandbox 60-day default expiration for tables and partitions.
- No streaming support.
- No BigQuery DML support.
- No BigQuery Data Transfer Service support.

The 60-day Sandbox expiration is an environment constraint, not an enterprise production retention policy. Future production deployment must redesign retention separately for RAW, CORE, and MART based on business, compliance, cost, and replay requirements.

Billing-free development should not claim to validate production streaming behavior. Future full-cloud integration in an explicitly approved Free Trial or other billing-enabled environment must validate capabilities unavailable in Sandbox.

## Production Considerations

Future production design must review:

- Data residency and organizational policy.
- Query cost and quota exposure.
- Partitioning, clustering, and retention.
- Access controls and read-only analytical access for agents.
- Dataset and table deletion safety.
- Backup, replay, and rebuild strategy.
- Observability across ingestion, processing, analytics, and agent workflows.
