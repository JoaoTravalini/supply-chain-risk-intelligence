# SupplyChain Sentinel

SupplyChain Sentinel is a production-oriented portfolio project for cloud-native supply-chain risk intelligence. It will combine synthetic but realistic supplier operational data with external risk signals, preserve provenance, calculate deterministic supplier risk scores, and use agentic AI to investigate and explain evidence without making the LLM the source of business truth.

## Current Status

The project has completed **Stage 5: BigQuery Data Architecture**. Stage 0 established the target architecture, Stage 1 established the minimal Python package bootstrap, Stage 2 established local quality tooling, Stage 3 documented the billing-free Google Cloud bootstrap, and Stage 4 established the OpenTofu foundation.

The repository now contains the minimal Python package scaffold, local quality tooling, project metadata, lockfile support, a bootstrap import test, billing-free Google Cloud bootstrap documentation, an OpenTofu root module foundation, provisioned BigQuery Sandbox RAW/CORE/MART datasets managed by OpenTofu, the Canonical Event v1 contract, and the Supplier v1 master-data contract. Billing remains disabled, Sandbox 60-day table and partition expiration is represented explicitly in development IaC, and physical BigQuery tables have not yet been defined. Stage 7B will generate a deterministic synthetic supplier dataset without implementing messaging.

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
- [Supplier Domain Contract](docs/domain/supplier.md)
- [Roadmap](docs/roadmap.md)
- [Architectural Decisions](docs/decisions)
- [GCP Project Bootstrap Runbook](docs/runbooks/gcp-project-bootstrap.md)
- [Infrastructure](infra/README.md)
