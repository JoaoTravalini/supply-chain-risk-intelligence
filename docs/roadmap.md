# Roadmap

The roadmap is intentionally staged so architecture, quality, infrastructure, data contracts, deterministic risk logic, agent workflows, and product experience are built in a controlled order.

Stages may be subdivided if their scope becomes too large.

## Foundation

0. Architecture & Engineering Contract
1. Python Project Bootstrap
2. Quality Toolchain & Local Configuration
3. GCP Account + Project Bootstrap
4. Infrastructure as Code Foundation

## Data Platform

5. BigQuery Data Architecture
6. Canonical Event Contract
7. Supplier Domain + Synthetic Dataset
8. External Data Adapters
9. Pub/Sub Messaging Pipeline
10. Event Processing + Idempotency + DLQ
11. RAW -> CORE -> MART Transformations
12. Deterministic Risk Engine

## Agentic AI

13. LangGraph State + Persistence
14. BigQuery Read Tool
15. SQL Security + Cost Guardrails
16. Investigation Workflow + Evidence
17. Validation + Human-in-the-loop

## Product & Production

18. Streamlit Application
19. Observability + Tests + Evals + CI/CD + Deployment

## Current Stage

The project is currently in Stage 1: Python Project Bootstrap. This stage establishes only the minimal Python packaging, runtime baseline, lockfile, and bootstrap import test.
