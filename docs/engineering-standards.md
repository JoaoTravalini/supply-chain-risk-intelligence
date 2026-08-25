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

## Events and Data Contracts

- Process events idempotently.
- Assume at-least-once message delivery.
- Version event schemas.
- Preserve provenance and source metadata.
- Prefer append-only RAW storage semantics unless a later ADR decides otherwise.
- Validate and normalize external data before publishing canonical events.

## Data Access

- Use parameterized SQL for dynamic values.
- Avoid unrestricted LLM-generated DDL or DML.
- Bound BigQuery queries through explicit limits, partition filters, projected columns, and cost-aware query design where appropriate.
- Treat BigQuery as the analytical system of record, not as transactional state storage for agent execution.

## Security

- Do not hardcode secrets.
- Do not commit service-account key files.
- Use managed secrets in deployed environments.
- Apply least-privilege IAM.
- Prefer separate workload identities for separate workloads.
- Keep agent access to analytical datasets read-only unless an explicit design decision grants write access.

## Observability

- Use structured logging for production code.
- Include relevant correlation identifiers in logs and emitted events.
- Design logs, traces, and metrics so investigations can cross service, data, and agent boundaries.

## Testing

- Add tests with business logic changes.
- Favor unit tests for deterministic domain behavior.
- Use contract tests for adapters and event schemas.
- Use integration tests where cloud, database, or messaging behavior must be verified.
- Use end-to-end tests for critical user workflows once the product surface exists.
- Use agent evaluations for LangGraph behavior once the investigation workflow exists.

## Documentation and Change Control

- Update documentation when architecture changes.
- Record major architecture changes as ADRs.
- Do not change accepted target technology decisions without an explicit ADR.
- Keep implementation details deferred until their planned stage when they have not yet been decided.
