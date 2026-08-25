# ADR 0008: Free-Tier and Cost-Aware Architecture

## Status

Accepted

## Context

SupplyChain Sentinel is a portfolio deployment intended to demonstrate production-oriented engineering while remaining practical to operate within free-tier-friendly constraints. Cost control must influence architecture from the beginning.

## Decision

Cost-aware architecture is a project requirement.

Future implementation must consider BigQuery bytes processed, partition pruning, query limits, Cloud Run scaling limits, minimal scheduled jobs, controlled external API usage, and bounded LLM usage.

## Consequences

- Query design must consider projected columns, partition filters, and bounded result sets.
- Workloads should avoid unnecessary scheduling, scaling, and background execution.
- External API and LLM usage should be limited, observable, and intentional.
- Cost controls are architectural requirements, not late-stage optimizations.

