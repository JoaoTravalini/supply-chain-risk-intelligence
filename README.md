# SupplyChain Sentinel

SupplyChain Sentinel is a production-oriented portfolio project for cloud-native supply-chain risk intelligence. It will combine synthetic but realistic supplier operational data with external risk signals, preserve provenance, calculate deterministic supplier risk scores, and use agentic AI to investigate and explain evidence without making the LLM the source of business truth.

## Current Status

The project is in **Stage 20: Final Integration + Audit**. Stages 0-19 implemented the target architecture, local quality tooling, BigQuery RAW/CORE/MART data platform, canonical events, Supplier domain model, external adapters, local Pub/Sub transport, idempotent processing and DLQ semantics, deployed development BigQuery warehouse objects, deterministic Supplier Risk Model v1, LangGraph investigation runtime, guarded BigQuery agent reads, Gemini-backed structured investigation boundary, deterministic validation, native human review, offline agent evaluations, Streamlit application, vendor-neutral observability, cloud-independent CI/CD, containerization, OpenTofu production infrastructure, and a dashboard-first Cloud Run deployment.

The production deployment is intentionally dashboard-first. The deployed Cloud Run service runs a frozen immutable Streamlit image in the runtime project `sc-sentinel-prod-7h2k9q`, remains private through IAM, accepts authenticated `run.app` access, uses request-based CPU allocation with minimum instances set to zero, and reads approved CORE/MART BigQuery data from the separate data project `supplychain-sentinel-646511`. Runtime BigQuery jobs execute in the runtime project; data reads remain fully qualified to the data project. The deployed dashboard and Supplier Explorer have rendered real BigQuery data. RAW access, public unauthenticated access, production Pub/Sub topology, managed PostgreSQL, Gemini runtime secrets, production AI investigation/HITL runtime, production scheduling, DLQ replay operations, and remote telemetry exporters remain intentionally gated.

The Stage 15 agent implementation is complete, and BigQuery/LangGraph/PostgreSQL integration reached the Gemini boundary; a provider-independent minimal text-only Gemini diagnostic reproduced the external provider/key capability blocker without Supplier or project context. Live Gemini provider validation must be repeated once provider/key capability is restored. Live environmental factors depend on qualifying CORE evidence.

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

The original development/data project remains billing-disabled. The separate production runtime project is billed only for explicitly approved production runtime resources and uses conservative cost controls such as Cloud Run scale-to-zero, request-based CPU allocation, bounded maximum instances, and BigQuery byte limits. The repository does not claim absolute zero production cost.

Canonical local quality checks are:

- `uv run ruff check .`
- `uv run ruff format --check .`
- `uv run mypy src tests`
- `uv run pytest`

## Run the Application

Start the local Streamlit application from the repository root:

```shell
uv run streamlit run src/supplychain/ui/app.py
```

The application uses the existing environment configuration for BigQuery, PostgreSQL-backed investigation state, and Gemini. Missing infrastructure configuration is presented as a safe unavailable state. The UI does not probe Gemini at startup; investigation execution requires an explicit user action, and the documented external Gemini provider/key capability blocker remains unresolved until live validation is repeated.

## Observability

Local observability is application-owned and vendor-neutral. Logs are structured JSON written to stdout, traces and metrics use OpenTelemetry SDK providers, and no remote telemetry exporter is configured by default. The observability runtime tracks bounded operation metadata and correlation identifiers while excluding credentials, DSNs, prompts, SQL text, provider bodies, raw evidence payloads, and checkpoint contents.

Telemetry tests use in-memory OpenTelemetry exporters/readers and captured JSON logs, so the observability contract is validated without a collector, cloud service, internet access, or live Gemini request.

## CI and Production Deployment

GitHub Actions CI validates repository quality from the lockfile without cloud credentials. The normal CI path runs Ruff, Ruff format, MyPy, Pytest, pre-commit, `uv lock --check`, and the deterministic agent evaluation command.

Infrastructure validation is separate and credential-free: OpenTofu formatting plus `init -backend=false` and `validate` for the development, bootstrap, and production roots. The production planning workflow is manual, plan-only, and uses GitHub OIDC federation through the bootstrapped Workload Identity Federation path. It does not run `tofu apply`.

The production Streamlit application is built as an immutable Cloud Run-compatible container. Local builds use:

```shell
docker build -t supplychain-sentinel:stage19a .
```

The image binds Streamlit to `0.0.0.0:${PORT}`, runs as a non-root user, includes only the required PostgreSQL client runtime library for `psycopg`, and contains no tracked secrets, local state, tests, docs, or Git metadata. Production deployment uses an immutable digest rather than `latest`.

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
- [Processing Coordinator](docs/processing/coordinator.md)
- [Processing Failure Classification](docs/processing/failures.md)
- [Retry And Dead-Letter Policy](docs/processing/retry-and-dead-letter.md)
- [Supplier Domain Contract](docs/domain/supplier.md)
- [Synthetic Supplier Dataset](docs/data/synthetic-suppliers.md)
- [BigQuery RAW/CORE Pipeline](docs/data/bigquery-pipeline.md)
- [Supplier Risk Model v1](docs/risk/risk-model-v1.md)
- [Risk MART](docs/data/risk-mart.md)
- [LangGraph Investigation Runtime](docs/agent/langgraph-runtime.md)
- [Guarded BigQuery Agent Data Access](docs/agent/bigquery-tools.md)
- [Evidence-Grounded Investigation Workflow](docs/agent/investigation-workflow.md)
- [Investigation Validation, Human Review, and Evaluation](docs/agent/human-review-and-evaluation.md)
- [Streamlit Application](docs/ui/streamlit-application.md)
- [Observability](docs/observability.md)
- [Production Architecture](docs/deployment/production-architecture.md)
- [Production Deployment Runbook](docs/deployment/runbook.md)
- [Cost and Safety](docs/deployment/cost-and-safety.md)
- [Roadmap](docs/roadmap.md)
- [Architectural Decisions](docs/decisions)
- [GCP Project Bootstrap Runbook](docs/runbooks/gcp-project-bootstrap.md)
- [Local PostgreSQL Agent State Runbook](docs/runbooks/postgres-agent-state.md)
- [Pub/Sub Emulator Runbook](docs/runbooks/pubsub-emulator.md)
- [Infrastructure](infra/README.md)
