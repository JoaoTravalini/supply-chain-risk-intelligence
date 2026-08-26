# Architecture

SupplyChain Sentinel is a cloud-native supply-chain risk intelligence platform. It combines synthetic but realistic supplier operational data with external risk signals, preserves data provenance, calculates deterministic supplier risk scores, and uses LangGraph to investigate risk with evidence-grounded AI assistance.

The primary objective is engineering depth rather than feature quantity. The architecture is designed to demonstrate cloud, data engineering, agentic AI, reliability, security, testing, observability, and maintainability practices.

## Architectural Principles

### Deterministic Business Truth

The LLM must not generate the authoritative supplier risk score.

Supplier risk scores and risk factors must come from deterministic, versioned, and testable business logic. The agent may retrieve data, investigate, correlate evidence, explain findings, summarize, and recommend. The agent may not invent authoritative business metrics.

### Event-Driven Ingestion

External information is normalized into canonical versioned events before entering the analytical platform.

The architecture assumes at-least-once message delivery. Downstream processing must therefore be idempotent or deduplicated by design.

### Analytical vs Transactional Storage

BigQuery is the analytical system of record.

BigQuery is not the transactional persistence store for LangGraph execution state. Persistent LangGraph checkpoints and thread state will use PostgreSQL through an abstraction compatible with a production persistent checkpointer.

### Explicit System Boundaries

External systems must be accessed through adapters or repositories. Domain and business logic should not directly depend on GCP SDKs, HTTP libraries, or LLM provider SDKs.

### Security by Default

Future implementation must follow least-privilege IAM, separate workload identities, no committed service-account key files, no hardcoded secrets, managed secrets in deployed environments, parameterized data access, and read-only agent access to analytical datasets unless explicitly designed otherwise.

### Cost-Aware Architecture

This project is intended to operate within free-tier-friendly constraints. Cost controls are architectural requirements rather than optional optimizations.

Future implementation must consider BigQuery bytes processed, partition pruning, query limits, Cloud Run scaling limits, minimal scheduled jobs, controlled external API usage, and bounded LLM usage.

### Observability

The future implementation must support correlation across system boundaries. Relevant identifiers include `event_id`, `correlation_id`, `request_id`, `investigation_id`, and `thread_id`.

Logging should be structured rather than plain unstructured print statements.

### Testing

Business logic must be testable independently from cloud infrastructure.

The future repository will contain appropriate unit tests, contract tests, integration tests, end-to-end tests, and agent evaluations. These are not created in Stage 0.

## Target Logical Architecture

External data sources:

- Weather and risk data.
- Seismic and event data.
- Synthetic operational supplier data.
- Additional external sources only after explicit architectural review.

Stage 8A provides the reusable synchronous HTTPS/JSON boundary that future
external source adapters will use. Provider-specific adapters, source payload
schemas, canonical event production, Pub/Sub publishing, and warehouse loading
are not implemented yet.

Target flow:

```text
External Sources
-> External HTTP boundary
-> Cloud Run ingestion workload
-> Canonical event validation and normalization
-> Google Cloud Pub/Sub
-> Event processor
-> BigQuery RAW
-> BigQuery CORE
-> BigQuery MART
-> Deterministic supplier risk engine
-> LangGraph investigation workflow
-> Streamlit application
```

A dead-letter path must exist for unprocessable messaging events.

Cloud Scheduler will eventually trigger scheduled workloads where appropriate.

## BigQuery Conceptual Layers

Physical schemas are intentionally deferred. Stage 0 defines only conceptual analytical layers.

### RAW

Purpose:

- Preserve source events.
- Retain provenance.
- Prefer append-only semantics.
- Support replay, debugging, and auditing.

### CORE

Purpose:

- Normalize data.
- Store typed and validated records.
- Deduplicate canonical events.
- Represent the canonical supplier-risk domain.

### MART

Purpose:

- Provide business-facing analytical models.
- Support supplier risk, risk factors, and historical trends.
- Optimize data for dashboards and agent queries.

Partitioning, clustering, and query-cost controls are future mandatory concerns.

## Supplier Risk Architecture

Supplier risk will eventually combine deterministic factors such as:

- Operational performance.
- Delivery reliability.
- Weather exposure.
- Seismic exposure.
- Supplier criticality.

The exact formula and weights are intentionally not defined in Stage 0.

Risk calculation must eventually expose:

- Total risk score.
- Component scores.
- Calculation timestamp.
- Model or rule version.
- Evidence and input references where appropriate.

This allows risk changes to be reproduced, audited, and explained.

## Agent Architecture

The intended logical LangGraph workflow is:

```text
START
-> Understand Request
-> Plan Investigation
-> Determine Required Evidence
-> Retrieve Evidence
-> Analyze Evidence
-> Validate
-> Respond OR Human Review
```

Future state is expected to represent concepts including:

- `investigation_id`
- `thread_id`
- User question
- Intent
- Investigation plan
- Requested tools
- Executed tools
- Analytical queries
- Evidence
- Risk factors
- Confidence
- Validation outcome
- Final answer

Python state models are intentionally not implemented in Stage 0.

The future design must support persistent checkpoints and interrupt/resume human-in-the-loop behavior.

## Planned User Experience

The intended Streamlit application areas are:

### Overview

Executive supplier-risk overview.

### Suppliers

Supplier profile, current risk, historical risk, and factor decomposition.

### Events

External and operational events with provenance.

### AI Investigation

Evidence-grounded investigation of supplier risk using the LangGraph workflow.

The UI is not implemented in Stage 0.

## Planned Technology Decisions

The current target technologies are:

- Python
- uv
- Pydantic
- Pytest
- Ruff
- MyPy
- Google Cloud Platform
- Pub/Sub
- BigQuery
- Cloud Run
- Cloud Scheduler
- LangGraph
- Gemini API
- PostgreSQL for persistent agent and checkpoint state
- Streamlit
- Docker
- OpenTofu
- GitHub Actions
- Google Cloud Workload Identity Federation
- Google Secret Manager

These are target choices. They may only be changed through an explicit architectural decision record. Exact package versions are intentionally deferred.

## Monorepo Target

The project will use one repository. Future deployable workloads may have separate entrypoints, but shared domain logic must not be duplicated across services.

The intended future repository organization is conceptual only:

```text
src/supplychain/
  domain/
  contracts/
  ingestion/
  processing/
  risk/
  data/
  agent/
  observability/
  config/

services/
  ingestion_job/
  event_processor/
  transformation_job/
  web/

sql/
  raw/
  core/
  mart/

tests/
  unit/
  contract/
  integration/
  e2e/

evals/

infra/

docs/
  decisions/
  runbooks/

.github/
```

These directories should be created only when their implementation stage requires them.

## Architectural Decision Records

The following ADRs are accepted for Stage 0:

- [ADR 0001: GCP as Primary Cloud Platform](decisions/0001-gcp-as-primary-cloud-platform.md)
- [ADR 0002: Pub/Sub Event-Driven Messaging](decisions/0002-pubsub-event-driven-messaging.md)
- [ADR 0003: BigQuery as Analytical Warehouse](decisions/0003-bigquery-as-analytical-warehouse.md)
- [ADR 0004: Deterministic Risk Engine Separate from Generative AI](decisions/0004-deterministic-risk-engine-separate-from-generative-ai.md)
- [ADR 0005: LangGraph with PostgreSQL-Backed Persistent State](decisions/0005-langgraph-with-postgresql-backed-persistent-state.md)
- [ADR 0006: Streamlit as Analytical and AI User Interface](decisions/0006-streamlit-as-analytical-and-ai-user-interface.md)
- [ADR 0007: Monorepo with Shared Domain Modules](decisions/0007-monorepo-with-shared-domain-modules.md)
- [ADR 0008: Free-Tier and Cost-Aware Architecture](decisions/0008-free-tier-and-cost-aware-architecture.md)
- [ADR 0009: OpenTofu as Infrastructure as Code Engine](decisions/0009-opentofu-as-infrastructure-as-code-engine.md)
