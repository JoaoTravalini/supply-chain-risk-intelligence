# ADR 0003: BigQuery as Analytical Warehouse

## Status

Accepted

## Context

The platform needs an analytical system of record for supplier operational data, external risk events, risk factors, historical trends, dashboards, and agent evidence retrieval. The system should support queryable analytical layers while maintaining provenance and auditability.

## Decision

BigQuery will be the analytical warehouse.

The conceptual layers are RAW, CORE, and MART:

- RAW preserves source events and provenance.
- CORE stores normalized, typed, validated, and deduplicated canonical records.
- MART provides business-facing analytical models for dashboards, risk factors, historical trends, and agent queries.

BigQuery will not be used as transactional persistence for LangGraph execution state.

## Consequences

- Data modeling must account for analytical access patterns, partitioning, clustering, and cost controls.
- RAW data should support replay, debugging, and audit scenarios.
- Agent access to BigQuery should be read-only unless a later decision explicitly grants write access.
- Transactional state must use a separate persistence mechanism.

