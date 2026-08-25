# ADR 0002: Pub/Sub Event-Driven Messaging

## Status

Accepted

## Context

External and operational risk signals need to enter the platform through a reliable ingestion path that supports decoupled processing, replay-oriented design, and failure handling. Message delivery should be compatible with cloud-native workloads.

## Decision

Google Cloud Pub/Sub will be the event-driven messaging backbone.

External information will be validated and normalized into canonical versioned events before publication. Consumers must assume at-least-once delivery and handle idempotency or deduplication by design. A dead-letter path must exist for unprocessable messages.

## Consequences

- Event contracts and schema versioning become core architectural concerns.
- Consumers cannot rely on exactly-once delivery semantics.
- Processing workloads must track stable event identifiers where appropriate.
- Failed or invalid messages must be observable and recoverable.
