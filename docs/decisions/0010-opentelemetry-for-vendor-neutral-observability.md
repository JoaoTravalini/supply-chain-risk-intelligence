# ADR 0010: OpenTelemetry for Vendor-Neutral Observability

## Status

Accepted

## Context

SupplyChain Sentinel needs production-grade logs, traces, and metrics before deployment work begins. The project should preserve portability and avoid coupling application code to a deployment vendor or observability backend.

## Decision

SupplyChain Sentinel will use OpenTelemetry API and SDK for tracing and metrics, with structured JSON logs emitted through Python's standard logging system.

The application owns an explicit observability runtime. Exporter selection, collector configuration, and remote telemetry transport are deferred to deployment work.

## Consequences

- Application services can be instrumented without replacing business semantics.
- Tests can use isolated in-memory OpenTelemetry exporters and readers.
- Local development works with no network telemetry exporter.
- Deployment-specific telemetry backends remain a Stage 19 concern.
- Telemetry is treated as a security boundary and must exclude secrets, prompts, SQL text, raw provider responses, raw evidence payloads, and checkpoint contents.
