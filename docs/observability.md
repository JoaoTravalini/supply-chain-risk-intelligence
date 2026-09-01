# Production-Grade Observability

Stage 18 establishes vendor-neutral observability for SupplyChain Sentinel before deployment-specific exporter choices are introduced.

## Architecture

The observability package lives under `src/supplychain/observability/` and provides:

- context-local correlation identifiers;
- structured JSON logging through Python's standard `logging` system;
- OpenTelemetry tracing;
- OpenTelemetry metrics;
- a safe diagnostics snapshot.

`ObservabilityRuntime` owns the OpenTelemetry `TracerProvider`, `MeterProvider`, tracer, meter, metric instruments, logger configuration, and service resource metadata. Tests can construct isolated runtimes with in-memory exporters/readers without replacing global OpenTelemetry providers.

By default, Stage 18 configures no network exporter. Logs remain useful on stdout, and traces/metrics are recorded locally by the configured runtime.

## Configuration

Non-secret environment settings:

- `SUPPLYCHAIN_SERVICE_NAME`, default `supplychain-sentinel`;
- `SUPPLYCHAIN_ENVIRONMENT`, default `development`;
- `SUPPLYCHAIN_LOG_LEVEL`, default `INFO`;
- `SUPPLYCHAIN_OBSERVABILITY_ENABLED`, default `true`.

Exporter endpoints, exporter credentials, and deployment wiring are deferred to Stage 19.

## Correlation Semantics

- `request_id`: one application/user/service operation, generated at explicit boundaries such as portfolio refresh, investigation run, review submission, or event-processing attempt.
- `correlation_id`: logical operation lineage. Canonical events preserve existing event metadata correlation IDs; investigations use the durable `investigation_id` as the correlation anchor.
- `event_id`: canonical event instance ID.
- `investigation_id`: durable investigation identity.
- `thread_id`: durable LangGraph checkpoint thread identity.

Context is implemented with `contextvars`, supports nesting, restores previous values after normal or exceptional exits, and avoids leaking identifiers between independent operations.

## Structured Log Contract

Application logs are one JSON object per record. Common fields include:

- UTC timestamp;
- severity;
- event name;
- component;
- service;
- environment;
- request/correlation/event/investigation/thread identifiers when bound;
- active trace/span IDs;
- bounded safe metadata such as operation, outcome, error category, exception class, provider model, status code, validation result, review decision, processing decision, estimated bytes, maximum bytes billed, and row count.

Business code should use the bounded structured logging helper rather than attaching arbitrary provider or infrastructure dictionaries.

## Tracing

Stable span names are used. IDs are attributes, never part of span names.

Instrumented spans include:

- `supplychain.bigquery.read`;
- `supplychain.portfolio.load`;
- `supplychain.event.process`;
- `supplychain.pubsub.publish`;
- `supplychain.pubsub.consume`;
- `supplychain.pubsub.ack`;
- `supplychain.pubsub.redelivery`;
- `supplychain.investigation.run`;
- `supplychain.investigation.model`;
- `supplychain.investigation.validate`;
- `supplychain.review.submit`.

Trace attributes are bounded and may include operation, Supplier ID, event ID, investigation ID, thread ID, provider model, validation outcome, review decision, and processing decision. They must not include prompts, questions, recommendations, evidence payloads, SQL, credentials, provider bodies, or checkpoint contents.

## Metrics

The metric vocabulary is intentionally small:

- `supplychain.operation.count`;
- `supplychain.operation.duration_ms`;
- `supplychain.bigquery.estimated_bytes`;
- `supplychain.bigquery.returned_rows`.

Metric attributes are bounded to fields such as component, operation, outcome, error category, review decision, processing decision, provider model, validation outcome, and validation failure code.

High-cardinality identifiers are forbidden in metric attributes:

- request ID;
- correlation ID;
- event ID;
- investigation ID;
- thread ID;
- Supplier ID;
- review ID.

## BigQuery Observability

Guarded BigQuery reads record dry-run outcome, budget rejection, estimated bytes, configured maximum bytes billed, duration, returned row count, and success/failure category. Telemetry does not include SQL text or query parameters.

Observability does not alter BigQuery safety behavior: dry-run, SELECT-only catalog usage, maximum bytes billed, finite timeout, and result bounds remain authoritative.

## Agent And HITL Observability

Investigation telemetry records run outcomes, provider/model boundary outcomes, safe provider failure category/class/status, deterministic validation pass/fail, bounded validation failure codes, HITL pending, and APPROVE/REJECT review submission outcomes.

Human review audit data remains in the application checkpoint state. Operational telemetry intentionally avoids reviewer free-text reason and does not place reviewer identifiers in metrics.

Human interrupts may last minutes, hours, or days, so Stage 18 does not keep an OpenTelemetry span open across the waiting period. Investigation execution and review submission/resume are separate spans correlated by durable `investigation_id` and `thread_id`.

## Event And Pub/Sub Observability

Event processing records bounded processing decisions such as new, duplicate, stale revision, newer revision, and revision conflict without changing ledger semantics or ACK ordering. Pub/Sub publish, pull, acknowledge, and redelivery-intent operations are instrumented without recording message bodies.

## Data Minimization

Telemetry must never contain:

- API keys;
- authorization headers;
- DSNs;
- passwords or tokens;
- full prompts or system instructions;
- user investigation questions;
- provider raw requests or responses;
- arbitrary evidence payloads;
- entire canonical event payloads;
- SQL text;
- BigQuery raw rows;
- LangGraph checkpoint contents.

Tests include sentinel values to verify covered telemetry paths do not serialize sensitive content.

## Diagnostics

The diagnostics snapshot reports configuration-level facts: service name, environment, service version, structured logging enabled, tracing enabled, metrics enabled, and external exporter configured yes/no.

Diagnostics are not live dependency health checks. Configuration presence must not be interpreted as Gemini, BigQuery, PostgreSQL, Pub/Sub, or exporter health.

## Stage 19 Boundary

Stage 19 owns deployment-specific exporter selection, remote telemetry transport, CI/CD wiring, production IAM, and production deployment. Stage 18 intentionally stops at vendor-neutral instrumentation and local verification.
