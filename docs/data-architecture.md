# Data Architecture

SupplyChain Sentinel uses a layered BigQuery analytical model. Stage 5 has provisioned the RAW, CORE, and MART dataset boundaries in BigQuery Sandbox through OpenTofu. It does not create tables, define schemas, load data, or implement transformations.

## Analytical Layers

### RAW

RAW preserves ingested source records and source fidelity wherever practical. It retains provenance and ingestion metadata, and supports replay, debugging, and auditing.

RAW is not the preferred user-facing query layer. Consumers should use CORE or MART when the required information has been validated and modeled there.

### CORE

CORE contains the canonical typed business representation. It is the boundary for normalized, validated, and deduplicated domain-oriented records.

CORE is the preferred source for reusable domain data and agent tools when MART does not yet provide the required analytical model.

### MART

MART contains business-facing analytical models. It supports supplier risk analytics, historical risk, factor decomposition, dashboards, and optimized consumption by Streamlit and LangGraph data tools.

MART should not be used as a raw ingestion landing area, and normal application workflows should not write directly to MART.

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

The Canonical Event v1 contract now exists as the platform boundary for future source normalization. Pub/Sub messaging, physical RAW tables, and ingestion processors are not implemented yet.

Canonical Events always carry stable source identity through `source.provider` and `source_event_id`. Future source adapters are responsible for deriving deterministic source IDs from provider-specific natural keys when an upstream source does not expose a native stable identifier.

The Supplier master-data contract now defines canonical supplier identity, category, criticality, location, exposure, lead time, dependency, and sourcing concentration. Canonical Supplier master data now exists as a versioned synthetic JSONL artifact validated through the Supplier v1 contract. It has not been loaded into BigQuery, no physical CORE supplier table exists yet, and warehouse representation remains deferred.

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
