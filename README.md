# SupplyChain Sentinel

Supply chains depend on many suppliers, regions, transport paths, and external conditions. A disruption does not become useful operational intelligence just because it appears in a weather feed, seismic catalog, or dashboard table; it has to be normalized, tied to supplier context, scored consistently, and made explainable enough for an operations team to act on.

SupplyChain Sentinel is a cloud-native supply-chain risk intelligence platform that aggregates supplier data and external risk signals, preserves provenance through canonical events, calculates auditable supplier risk, and presents the current portfolio state through a production Streamlit dashboard on Google Cloud Run.

The core design choice is separation of authority: deterministic, versioned business logic owns supplier risk scores, while LangGraph and Gemini support evidence-grounded investigation and explanation. The LLM can retrieve, analyze, contextualize, and recommend; it does not calculate or define authoritative risk.

## Highlights

- Cloud-native dashboard deployed privately on Cloud Run.
- BigQuery RAW -> CORE -> MART analytical architecture.
- Deterministic Supplier Risk Model v1 with versioned, testable scoring.
- Canonical event contracts for source normalization and provenance.
- Event-processing semantics for idempotency, revision handling, retries, and DLQ paths.
- Guarded BigQuery access with static SQL, dry-run cost checks, bounded results, and no RAW runtime access.
- LangGraph investigation architecture with Gemini, validation, persistent state design, and human review.
- OpenTofu infrastructure for development, bootstrap, and production roots.
- Vendor-neutral observability with structured logs and OpenTelemetry traces/metrics.
- CI/CD quality gates with Ruff, MyPy, Pytest, pre-commit, locked dependencies, and deterministic agent evaluations.
- Cost-aware production posture: request-based Cloud Run CPU, min instances `0`, bounded max instances, and gated expensive resources.

## Production Status

### Deployed

- Private Streamlit dashboard on Cloud Run: `supplychain-sentinel`.
- Runtime project: `sc-sentinel-prod-7h2k9q`.
- Data project: `supplychain-sentinel-646511`.
- Immutable production image in Artifact Registry:
  `us-central1-docker.pkg.dev/sc-sentinel-prod-7h2k9q/supplychain-sentinel/app@sha256:dbe3906511257fa5983e6eda46ee615a193bac2e72bcefac084a549b1553494f`.
- Real BigQuery CORE/MART data rendered by Risk Portfolio and Supplier Explorer.
- Runtime BigQuery jobs execute in the runtime project.
- Approved CORE/MART reads come from the separate data project.
- Runtime service account follows least-privilege intent.
- Cloud Run ingress allows authenticated `run.app` access.
- `allow_unauthenticated = false`; no public `allUsers` invoker access.
- Cloud Run request-based CPU allocation with `cpu_idle = true`.
- Cloud Run min instances `0`, max instances `3`.
- Infrastructure managed with OpenTofu.

### Implemented, Production-Gated

- LangGraph + Gemini investigation runtime.
- Managed PostgreSQL agent checkpoint state.
- Production Pub/Sub topology.
- Secret Manager AI/runtime secrets.
- Production HITL investigation runtime.
- Scheduling.
- DLQ replay operations.
- Remote telemetry exporters.

These capabilities are implemented in the repository but intentionally inactive in the current production deployment. Production AI investigation is not enabled, managed PostgreSQL is not deployed, and Gemini live production investigation is not active.

## Engineering Quality

Final validated project quality:

- Tests: `694 passed`, `4 skipped`.
- Coverage: `88%`.
- Deterministic agent evaluation: `6/6 passed`.
- Risk immutability: `100%`.
- Evidence integrity: `100%`.
- HITL routing: `100%`.
- Security boundary: `100%`.

Quality gates:

- Ruff linting.
- Ruff format check.
- MyPy strict typing.
- Pytest with coverage.
- pre-commit.
- `uv lock --check`.
- Deterministic agent evaluation command.

## Tech Stack

### Data & Cloud

- BigQuery
- Google Cloud
- Cloud Run
- Pub/Sub
- Artifact Registry

### AI & Application

- Python 3.13
- LangGraph
- Gemini
- Streamlit
- Pydantic

### Persistence & Infrastructure

- PostgreSQL
- OpenTofu
- Docker

### Engineering

- GitHub Actions
- OpenTelemetry
- Pytest
- Ruff
- MyPy
- uv

## Architecture

The analytical platform is built around explicit contracts and one-way data modeling:

```text
External signals / supplier data
        |
        v
Canonical event contracts
        |
        v
Event processing and idempotency
        |
        v
BigQuery RAW -> CORE -> MART
        |
        v
Deterministic risk engine
        |
        v
Streamlit risk analytics
```

The investigation architecture is separate from the authoritative scoring path:

```text
Approved analytical evidence
        |
        v
Guarded BigQuery data access
        |
        v
LangGraph investigation workflow
        |
        v
Gemini explanation
        |
        v
Deterministic validation / HITL
```

The first path is deployed for dashboard analytics. The second path is implemented and validated offline, but production execution is gated until Gemini runtime secrets and persistent production PostgreSQL are explicitly approved.

## AI Safety / Guardrails

This is not an "LLM calculates a score" project. Authoritative supplier risk metrics come from deterministic, versioned business logic and MART data. Gemini is used only behind a bounded model abstraction for investigation and explanation.

Guardrails include:

- static allowlisted BigQuery operations;
- no arbitrary SQL interface;
- no RAW access for runtime dashboards or agent reads;
- bounded model context;
- evidence citation allowlisting;
- deterministic validation before human review;
- HITL approve/reject workflow;
- PostgreSQL-backed persistent state architecture;
- offline deterministic evaluation harness.

## Security & Cost Controls

- No service-account JSON credentials in the repository or container.
- GitHub OIDC / Workload Identity Federation design for production planning.
- Private Cloud Run by default.
- `allow_unauthenticated = false`.
- Runtime identity has job execution in the runtime project and dataset-level CORE/MART read access in the data project.
- No production RAW access for the runtime identity.
- Secrets are gated behind agent runtime.
- Cloud SQL access is gated behind managed PostgreSQL.
- Cloud Run scales to zero with request-based CPU allocation.
- BigQuery reads use dry-run checks and maximum bytes billed.
- Pub/Sub, Cloud SQL, agent runtime, Gemini secrets, and telemetry exporters remain gated.

Production is cost-controlled, not guaranteed free.

## Running Locally

Install dependencies from the lockfile and run the Streamlit app:

```shell
uv sync
uv run streamlit run src/supplychain/ui/app.py
```

The app uses environment configuration for BigQuery, PostgreSQL-backed investigation state, and Gemini. Missing infrastructure configuration is shown as a safe unavailable state. The UI does not probe Gemini at startup; investigation execution requires an explicit user action.

Common quality checks:

```shell
uv run ruff check .
uv run ruff format --check .
uv run mypy src tests
uv run pytest
uv run python -m supplychain.agent.evaluation
```

## CI/CD and Deployment

GitHub Actions runs cloud-independent quality gates from the lockfile. Infrastructure validation is separate and uses OpenTofu formatting plus `init -backend=false` and `validate` for the development, bootstrap, and production roots.

Production planning is manual and plan-only. The workflow uses GitHub OIDC through Workload Identity Federation and does not run `tofu apply`. Production deployment uses immutable container image digests rather than `latest`.

The production container:

- uses Python 3.13;
- installs locked runtime dependencies with `uv`;
- runs as a non-root user;
- includes only `libpq5` as the required PostgreSQL client runtime library for `psycopg`;
- binds Streamlit to `0.0.0.0:${PORT}`;
- excludes tests, docs, infra, local state, Git metadata, and secrets.

## Documentation

### Architecture

- [Architecture](docs/architecture.md)
- [Data Architecture](docs/data-architecture.md)
- [Engineering Standards](docs/engineering-standards.md)
- [Roadmap](docs/roadmap.md)
- [Architectural Decisions](docs/decisions)

### Data & Risk

- [Canonical Event Contract](docs/contracts/canonical-event.md)
- [Weather Observation Contract](docs/contracts/weather-observation.md)
- [Seismic Event Contract](docs/contracts/seismic-event.md)
- [Supplier Domain Contract](docs/domain/supplier.md)
- [Synthetic Supplier Dataset](docs/data/synthetic-suppliers.md)
- [BigQuery RAW/CORE Pipeline](docs/data/bigquery-pipeline.md)
- [Supplier Risk Model v1](docs/risk/risk-model-v1.md)
- [Risk MART](docs/data/risk-mart.md)

### Messaging & Processing

- [Pub/Sub Messaging](docs/messaging/pubsub.md)
- [Processing Idempotency Semantics](docs/processing/idempotency.md)
- [Processing Ledger](docs/processing/ledger.md)
- [Processing Coordinator](docs/processing/coordinator.md)
- [Processing Failure Classification](docs/processing/failures.md)
- [Retry And Dead-Letter Policy](docs/processing/retry-and-dead-letter.md)

### Integrations

- [External HTTP Boundary](docs/integrations/http-boundary.md)
- [Open-Meteo Weather Adapter](docs/integrations/open-meteo.md)
- [USGS Seismic Adapter](docs/integrations/usgs.md)

### Agentic AI

- [LangGraph Investigation Runtime](docs/agent/langgraph-runtime.md)
- [Guarded BigQuery Agent Data Access](docs/agent/bigquery-tools.md)
- [Evidence-Grounded Investigation Workflow](docs/agent/investigation-workflow.md)
- [Investigation Validation, Human Review, and Evaluation](docs/agent/human-review-and-evaluation.md)

### UI & Observability

- [Streamlit Application](docs/ui/streamlit-application.md)
- [Observability](docs/observability.md)

### Deployment

- [Production Architecture](docs/deployment/production-architecture.md)
- [Production Deployment Runbook](docs/deployment/runbook.md)
- [Cost and Safety](docs/deployment/cost-and-safety.md)
- [Infrastructure](infra/README.md)

### Runbooks

- [GCP Project Bootstrap Runbook](docs/runbooks/gcp-project-bootstrap.md)
- [Local PostgreSQL Agent State Runbook](docs/runbooks/postgres-agent-state.md)
- [Pub/Sub Emulator Runbook](docs/runbooks/pubsub-emulator.md)
