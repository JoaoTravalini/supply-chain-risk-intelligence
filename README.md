# SupplyChain Sentinel

SupplyChain Sentinel is a production-oriented portfolio project for cloud-native supply-chain risk intelligence. It will combine synthetic but realistic supplier operational data with external risk signals, preserve provenance, calculate deterministic supplier risk scores, and use agentic AI to investigate and explain evidence without making the LLM the source of business truth.

## Current Status

The project has completed **Stage 10B: Persistent Processing Ledger & Revision-Aware Resolution**. Stage 0 established the target architecture, Stage 1 established the minimal Python package bootstrap, Stage 2 established local quality tooling, Stage 3 documented the billing-free Google Cloud bootstrap, Stage 4 established the OpenTofu foundation, Stage 5 established the BigQuery data architecture, Stage 6 introduced the Canonical Event v1 contract, Stage 7 introduced the Supplier v1 domain contract plus deterministic synthetic Supplier data, Stage 8A introduced the reusable external HTTP boundary, Stage 8B introduced the Open-Meteo weather adapter, Stage 8C introduced the USGS seismic adapter, Stage 9 introduced the local Pub/Sub messaging pipeline, and Stage 10A introduced processing identity and source-content fingerprints.

The repository now contains the minimal Python package scaffold, local quality tooling, project metadata, lockfile support, a bootstrap import test, billing-free Google Cloud bootstrap documentation, an OpenTofu root module foundation, provisioned BigQuery Sandbox RAW/CORE/MART datasets managed by OpenTofu, the Canonical Event v1 contract, the Supplier v1 master-data contract, a deterministic synthetic Supplier dataset, a reusable synchronous HTTP boundary, Open-Meteo and USGS adapters that canonicalize provider observations into Canonical Events, local-emulator-only Pub/Sub publisher and pull-consumer transport for `canonical-events-v1` and `canonical-events-processing-v1`, pure processing semantics for `NEW`, `DUPLICATE`, and `REVISION_CANDIDATE`, and a local SQLite processing ledger for successful-state idempotency and revision-aware resolution. Billing remains disabled, Sandbox 60-day table and partition expiration is represented explicitly in development IaC, and physical BigQuery tables have not yet been defined. Provider event persistence to RAW/CORE, processing retries, ACK/NACK policy, DLQ behavior, and warehouse loading remain deferred.

## Project Goals

- Ingest external and operational risk events through an event-driven architecture.
- Preserve event provenance, metadata, and replayability.
- Store analytical data in BigQuery RAW, CORE, and MART layers.
- Calculate deterministic, versioned, and auditable supplier risk scores.
- Support LangGraph investigations with persistent state and human review.
- Expose risk analytics through a Streamlit analytical and AI interface.
- Demonstrate enterprise-style engineering depth across reliability, security, testing, observability, maintainability, and cost control.

## High-Level Architecture

External sources feed Cloud Run ingestion workloads, which validate and normalize canonical events before publishing to Pub/Sub. Event processors write analytical data into BigQuery RAW, CORE, and MART layers. A deterministic risk engine calculates supplier risk. LangGraph workflows retrieve and analyze evidence, then Streamlit exposes dashboards and AI-assisted investigations.

The LLM explains evidence and supports investigation. It does not define authoritative business metrics.

## Engineering Philosophy

The project favors deterministic business logic, explicit system boundaries, cloud-native deployment practices, least-privilege security, structured observability, cost-aware operation, and tests that keep business logic independent from infrastructure.

During the current development phase, no Cloud Billing Account is linked to the Google Cloud project. Development starts with billing-free or local paths such as BigQuery Sandbox when introduced, local Pub/Sub emulation when introduced, and local execution for application services.

Canonical local quality checks are:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests`
- `uv run pytest`

## Documentation

- [Architecture](docs/architecture.md)
- [Data Architecture](docs/data-architecture.md)
- [Engineering Standards](docs/engineering-standards.md)
- [Canonical Event Contract](docs/contracts/canonical-event.md)
- [Weather Observation Contract](docs/contracts/weather-observation.md)
- [Seismic Event Contract](docs/contracts/seismic-event.md)
- [External HTTP Boundary](docs/integrations/http-boundary.md)
- [Open-Meteo Weather Adapter](docs/integrations/open-meteo.md)
- [USGS Seismic Adapter](docs/integrations/usgs.md)
- [Pub/Sub Messaging](docs/messaging/pubsub.md)
- [Processing Idempotency Semantics](docs/processing/idempotency.md)
- [Processing Ledger](docs/processing/ledger.md)
- [Supplier Domain Contract](docs/domain/supplier.md)
- [Synthetic Supplier Dataset](docs/data/synthetic-suppliers.md)
- [Roadmap](docs/roadmap.md)
- [Architectural Decisions](docs/decisions)
- [GCP Project Bootstrap Runbook](docs/runbooks/gcp-project-bootstrap.md)
- [Pub/Sub Emulator Runbook](docs/runbooks/pubsub-emulator.md)
- [Infrastructure](infra/README.md)
