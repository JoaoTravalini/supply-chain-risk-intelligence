# SupplyChain Sentinel

SupplyChain Sentinel is a production-oriented portfolio project for cloud-native supply-chain risk intelligence. It will combine synthetic but realistic supplier operational data with external risk signals, preserve provenance, calculate deterministic supplier risk scores, and use agentic AI to investigate and explain evidence without making the LLM the source of business truth.

## Current Status

The project is in **Stage 0: Architecture & Engineering Contract**. This stage defines the target architecture, engineering standards, roadmap, and major architectural decisions before implementation begins.

No application code, dependency configuration, cloud resources, infrastructure code, tests, or CI/CD workflows have been created yet.

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

## Documentation

- [Architecture](docs/architecture.md)
- [Engineering Standards](docs/engineering-standards.md)
- [Roadmap](docs/roadmap.md)
- [Architectural Decisions](docs/decisions)

