# ADR 0007: Monorepo with Shared Domain Modules

## Status

Accepted

## Context

The platform will eventually contain multiple workloads, including ingestion, event processing, transformations, risk calculation, agent workflows, and a web interface. These workloads must share contracts and domain logic without duplication.

## Decision

The project will use one repository.

Future deployable workloads may have separate entrypoints, but shared domain logic must live in shared modules rather than being copied across services.

## Consequences

- Repository organization must support shared domain code and separate deployable workloads.
- Boundaries between domain, adapters, services, data access, and UI code must remain explicit.
- Tooling and CI can be centralized when implementation begins.
- Application directories should be created only when their implementation stage requires them.

