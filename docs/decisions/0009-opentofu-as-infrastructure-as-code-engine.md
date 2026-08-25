# ADR 0009: OpenTofu as Infrastructure as Code Engine

## Status

Accepted

## Context

SupplyChain Sentinel will eventually require reviewable and reproducible cloud infrastructure changes. Infrastructure definitions should be declarative and versioned so future resource changes can be planned, reviewed, and audited before being applied.

## Decision

OpenTofu will be the project's Infrastructure as Code engine.

OpenTofu provides declarative IaC, reproducible infrastructure plans, open-source governance, compatibility with the provider ecosystem, and reviewable infrastructure changes.

## Consequences

- Infrastructure changes should be represented as OpenTofu configuration when an IaC definition is appropriate.
- Provider versions must be constrained and locked.
- State files, plan files, credentials, and environment-specific tfvars must not be committed.
- Future applies require explicit developer approval and reviewed plans.
- Stage 4 establishes the IaC foundation but provisions no cloud resources.
