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
   - 8A. External Integration Foundation
   - 8B. Open-Meteo Weather Adapter
   - 8C. USGS Seismic Adapter
9. Pub/Sub Messaging Pipeline
   - 9A. Local Pub/Sub Foundation & Canonical Event Publisher
   - 9B. Subscription / Pull Consumer Transport & Local End-to-End Messaging
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

Stage 9: Pub/Sub Messaging Pipeline is complete. Stage 9A added local Pub/Sub emulator safety configuration, deterministic Canonical Event serialization, derived message attributes, an emulator-only canonical topic bootstrap, and a Canonical Event publisher for `canonical-events-v1`. Stage 9B added the `canonical-events-processing-v1` pull subscription, Canonical Event deserialization, attribute integrity validation, synchronous pull consumer, explicit acknowledgement, and a redelivery transport primitive.

Provider data is not persisted. Processing idempotency, duplicate suppression, retry policy, DLQ behavior, physical BigQuery external-event tables, warehouse loading, transformations, revision-aware CORE processing, and risk scoring remain deferred.
