# SupplyChain Sentinel

SupplyChain Sentinel is a production-oriented portfolio project for cloud-native supply-chain risk intelligence. It will combine synthetic but realistic supplier operational data with external risk signals, preserve provenance, calculate deterministic supplier risk scores, and use agentic AI to investigate and explain evidence without making the LLM the source of business truth.

## Current Status

The project has completed implementation for **Stage 19A: CI/CD + Containerization + Production IaC Preparation**. Stage 0 established the target architecture, Stage 1 established the minimal Python package bootstrap, Stage 2 established local quality tooling, Stage 3 documented the billing-free Google Cloud bootstrap, Stage 4 established the OpenTofu foundation, Stage 5 established the BigQuery data architecture, Stage 6 introduced the Canonical Event v1 contract, Stage 7 introduced the Supplier v1 domain contract plus deterministic synthetic Supplier data, Stage 8A introduced the reusable external HTTP boundary, Stage 8B introduced the Open-Meteo weather adapter, Stage 8C introduced the USGS seismic adapter, Stage 9 introduced the local Pub/Sub messaging pipeline, Stage 10 introduced processing idempotency/failure policy, Stage 11 deployed the Sandbox-compatible RAW/CORE BigQuery pipeline after human approval of the saved OpenTofu plan, Stage 12 deployed the MART risk current/history tables after human approval of the saved OpenTofu plan, Stage 13 introduced a real minimal LangGraph investigation graph with PostgreSQL-backed checkpoint persistence, Stage 14 introduced allowlisted read-only BigQuery agent data tools with SQL and cost guardrails, Stage 15 connected the durable workflow to guarded CORE/MART retrieval and Gemini structured analysis, Stage 16 added deterministic report validation, native LangGraph human review, and offline deterministic agent evaluations, Stage 17 added the Streamlit presentation layer for portfolio risk, Supplier inspection, AI investigation, and human review, Stage 18 added vendor-neutral observability, and Stage 19A added cloud-independent CI, production containerization, and reviewable production OpenTofu preparation.

The repository now contains the minimal Python package scaffold, local quality tooling, project metadata, lockfile support, a bootstrap import test, billing-free Google Cloud bootstrap documentation, an OpenTofu root module foundation, BigQuery Sandbox RAW/CORE/MART datasets managed by OpenTofu, the Canonical Event v1 contract, the Supplier v1 master-data contract, a deterministic synthetic Supplier dataset, a reusable synchronous HTTP boundary, Open-Meteo and USGS adapters that canonicalize provider observations into Canonical Events, local-emulator-only Pub/Sub publisher and pull-consumer transport, processing idempotency/revision/failure policy, local native Pub/Sub DLQ topology, deployed BigQuery RAW/CORE table/view definitions, a batch-load warehouse runtime boundary, the deterministic Supplier Risk Model v1 with deployed MART current/history tables, the Stage 13 LangGraph investigation runtime with local PostgreSQL checkpoint support, the Stage 14 guarded BigQuery read boundary, the Stage 15 bounded investigation workflow with Gemini structured output validation, the Stage 16 validation/HITL/evaluation layer, the Stage 17 Streamlit application, the Stage 18 observability runtime, GitHub Actions quality/infra validation workflows, a production Streamlit container, and unapplied production OpenTofu bootstrap/production roots. Billing remains disabled, Sandbox 60-day table and partition expiration is represented explicitly in development IaC, the Supplier snapshot was loaded for validation, one synthetic CanonicalEvent was appended to RAW for validation, and one full 120-Supplier Stage 12 assessment batch was loaded to MART for validation. Stage 15 implementation is complete, and BigQuery/LangGraph/PostgreSQL integration reached the Gemini boundary; a provider-independent minimal text-only Gemini diagnostic reproduced the external capability blocker without Supplier or project context. Live Gemini provider validation must be repeated once provider/key capability is restored. Live environmental factors depend on available CORE evidence; production bootstrap, production apply/deployment, production scheduling, DLQ consumption/replay operations, and telemetry exporter deployment remain deferred.

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

## Run the Application

Start the local Streamlit application from the repository root:

```shell
uv run streamlit run src/supplychain/ui/app.py
```

The application uses the existing environment configuration for BigQuery, PostgreSQL-backed investigation state, and Gemini. Missing infrastructure configuration is presented as a safe unavailable state. The UI does not probe Gemini at startup; investigation execution requires an explicit user action, and the documented external Gemini provider/key capability blocker remains unresolved until live validation is repeated.

## Observability

Local observability is application-owned and vendor-neutral. Logs are structured JSON written to stdout, traces and metrics use OpenTelemetry SDK providers, and no remote telemetry exporter is configured by default. The observability runtime tracks bounded operation metadata and correlation identifiers while excluding credentials, DSNs, prompts, SQL text, provider bodies, raw evidence payloads, and checkpoint contents.

Telemetry tests use in-memory OpenTelemetry exporters/readers and captured JSON logs, so the observability contract is validated without a collector, cloud service, internet access, or live Gemini request.

## CI and Deployment Preparation

GitHub Actions CI validates repository quality from the lockfile without cloud credentials. The normal CI path runs Ruff, Ruff format, MyPy, Pytest, pre-commit, `uv lock --check`, and the deterministic agent evaluation command.

Infrastructure validation is separate and credential-free: OpenTofu formatting plus `init -backend=false` and `validate` for the development, bootstrap, and production roots. The production planning workflow is manual, plan-only, and designed for future GitHub OIDC federation after bootstrap. It does not run `tofu apply`.

The Streamlit application can be built locally as a container:

```shell
docker build -t supplychain-sentinel:stage19a .
```

The image is Cloud Run-compatible, binds Streamlit to `0.0.0.0:${PORT}`, runs as a non-root user, and contains no tracked secrets, local state, tests, docs, or Git metadata.

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
