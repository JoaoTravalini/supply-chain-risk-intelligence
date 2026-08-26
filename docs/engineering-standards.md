# Engineering Standards

These standards define future project conventions. They are part of the Stage 0 engineering contract and apply when implementation begins.

## Time and Identity

- Store and exchange timestamps in UTC.
- Include correlation identifiers across system boundaries where appropriate, including concepts such as `event_id`, `correlation_id`, `request_id`, `investigation_id`, and `thread_id`.
- Use deterministic IDs where appropriate to support idempotency, deduplication, replay, and auditability.

## Python and Type Safety

- The current Python runtime baseline is Python 3.13.x.
- Project metadata must constrain Python with `requires-python = ">=3.13,<3.14"`.
- The project-level `.python-version` targets `3.13` and must not pin a patch release.
- Use type hints for production Python code.
- Prefer explicit data models at system boundaries.
- Use Pydantic validation at system boundaries where external, serialized, or user-provided data enters the system.
- Keep business logic testable without cloud services, network calls, or LLM calls.

## System Boundaries

- Access external systems through adapters, repositories, or equivalent boundary abstractions.
- Keep domain logic independent from GCP SDKs, HTTP clients, database clients, and LLM provider SDKs.
- Use dependency inversion for external providers.
- Keep changes small and focused.
- External HTTP access must use the project boundary wrapper, bounded timeouts, bounded retries, structured query parameters, HTTPS by default, and project-specific exceptions.
- External source exceptions must preserve only safe context such as method, status, attempt count, and URL origin/path. Response bodies and query strings must not be stored in exception context.
- Provider adapters must validate provider response metadata, including units and timestamps, before constructing canonical payloads.

## Events and Data Contracts

- Process events idempotently.
- Assume at-least-once message delivery.
- Version event schemas.
- Breaking contract changes require an explicit version strategy.
- Preserve provenance and source metadata.
- Prefer append-only RAW storage semantics unless a later ADR decides otherwise.
- Validate and normalize external data before publishing canonical events.
- Canonical event timestamps must be timezone-aware and normalized to UTC.
- Event instance identity and logical idempotency identity must remain separate.
- Canonical Events must always include stable source identity; source adapters own provider-specific natural-key derivation when native source IDs are absent.
- Logical idempotency identity must use only stable source identity fields, event type, and event time.
- Provider-derived source identities must exclude entity enrichment, correlation lineage, ingestion time, delivery identity, and measurement values unless a later provider contract explicitly changes that identity model.
- When a provider exposes both stable event identity and revision/update time, adapters must preserve both concepts separately and must not fold revision time into logical deduplication identity.
- Entity enrichment must not redefine source-event identity.
- Producer and source metadata must never contain credentials or secrets.
- Pub/Sub message data is authoritative over message attributes.
- Pub/Sub transport message IDs must not be treated as business identities.
- Messaging consumers must assume possible redelivery.
- Real cloud messaging resources must be managed through IaC rather than application startup.
- Local messaging emulator bootstrap must fail closed when emulator configuration is missing or unsafe.
- Message attributes must be derived from validated events and must not duplicate arbitrary payload or unsafe metadata.

## Domain Contracts

- Canonical master-data contracts must be versioned and validated at system boundaries.
- Master data and operational observations must remain separate.
- Synthetic portfolio fixtures must be deterministic, reproducible, and generated without external network collection.
- Generated domain data must pass the relevant domain contract validation before use.
- Committed generated datasets must include integrity metadata and checksum validation.

## Data Access

- Use parameterized SQL for dynamic values.
- Avoid unrestricted LLM-generated DDL or DML.
- Bound BigQuery queries through explicit limits, partition filters, projected columns, and cost-aware query design where appropriate.
- Treat BigQuery as the analytical system of record, not as transactional state storage for agent execution.
- Analytical layer boundaries must remain explicit across RAW, CORE, and MART.
- Production consumers should not casually depend on RAW when validated CORE or business-facing MART data exists.
- Future physical table designs must justify partitioning and clustering choices per table.
- Destructive dataset behavior must be reviewed before infrastructure changes are applied.
- BigQuery query bytes, quotas, and cost behavior are first-class design concerns.

## Security

- Do not hardcode secrets.
- Do not commit service-account key files.
- Use managed secrets in deployed environments.
- Apply least-privilege IAM.
- Prefer separate workload identities for separate workloads.
- Keep agent access to analytical datasets read-only unless an explicit design decision grants write access.
- During the billing-free development phase, do not link a Cloud Billing Account to the project.
- BigQuery Sandbox retention behavior must be represented explicitly in development infrastructure when it affects drift detection, but it must not be treated as a production retention policy.
- A future decision to enable billing requires explicit developer approval, service pricing review, security controls review, quota and limit review, and review of exposure to unintended charges.
- Cloud Billing budgets may support monitoring and alerts, but they must not be treated as hard spending caps.

## Billing-Free Development

- BigQuery analytical development will initially use BigQuery Sandbox when introduced.
- Pub/Sub development will initially use the local Google Cloud Pub/Sub emulator before any managed Pub/Sub deployment.
- Python application services, Streamlit, and LangGraph will initially run locally during development.
- PostgreSQL will use a local or explicitly free-tier development option when that stage arrives.
- Cloud Run and other managed deployment infrastructure are deferred until a later deployment decision.
- Local emulator and cloud adapters should remain behind explicit system boundaries so domain logic does not need to be rewritten for deployment.

## Infrastructure as Code

- Infrastructure changes must be declarative when an IaC definition is appropriate.
- Do not hand-create application infrastructure that should be managed through OpenTofu.
- Provider versions must be constrained in configuration and locked in `.terraform.lock.hcl`.
- OpenTofu state, plan files, credentials, and real tfvars files must never be committed.
- Secrets must not be intentionally placed in tfvars or state.
- `tofu fmt` and `tofu validate` are mandatory for infrastructure changes.
- `tofu apply` must never be treated as an automatic local validation step.
- Future plans must be reviewed before applies.

## Observability

- Use structured logging for production code.
- Include relevant correlation identifiers in logs and emitted events.
- Design logs, traces, and metrics so investigations can cross service, data, and agent boundaries.

## Testing

- Add tests with business logic changes.
- Domain contract changes must include validation and schema drift tests.
- Favor unit tests for deterministic domain behavior.
- Use contract tests for adapters and event schemas.
- Use integration tests where cloud, database, or messaging behavior must be verified.
- Use end-to-end tests for critical user workflows once the product surface exists.
- Use agent evaluations for LangGraph behavior once the investigation workflow exists.

## Local Quality Gate

- Ruff is the project formatter and linter.
- MyPy runs in strict mode against `src/` and `tests/`.
- Pytest is the canonical test runner.
- Pytest coverage measures the `supplychain` package and reports missing lines.
- Future Python stages are expected to pass `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy src tests`, and `uv run pytest`.
- Pre-commit runs repository hygiene checks plus Ruff lint and format checks before commits.

## Documentation and Change Control

- Update documentation when architecture changes.
- Record major architecture changes as ADRs.
- Do not change accepted target technology decisions without an explicit ADR.
- Keep implementation details deferred until their planned stage when they have not yet been decided.
