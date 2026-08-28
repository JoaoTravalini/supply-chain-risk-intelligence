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
   - 10A. Processing Decision Contract & Source Content Fingerprints
   - 10B. Persistent Idempotency Ledger & Revision-Aware Decisions
   - 10C. Pub/Sub Processing Coordinator, Failure Policy & DLQ
     - 10C.1. Processing Coordinator & Safe ACK Ordering
     - 10C.2A. Processing Failure Classification Contract
     - 10C.2B. Retry Budget, Redelivery, Poison Handling & DLQ
      - 10C.2B.1. Dead-Letter Retention & Semantics Hardening
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

Stage 10 is complete. Stage 10A adds pure processing decision semantics, deterministic source-content fingerprints, a minimal prior-record value object, and local classifier behavior for `NEW`, `DUPLICATE`, and `REVISION_CANDIDATE`. Stage 10B adds the local persistent processing ledger, schema version 1, revision-marker extraction for USGS seismic events, and ledger-aware `NEW`, `DUPLICATE`, `NEWER_REVISION`, `STALE_REVISION`, and `REVISION_CONFLICT` resolution. Stage 10C.1 adds a one-message processing coordinator for valid Canonical Events with safe handler, ledger `record_success`, and ACK ordering. Stage 10C.2A adds failure classification for declared handler failures, unexpected exceptions, and revision conflicts without transport disposition. Stage 10C.2B adds bounded redelivery/dead-letter disposition policy, native local Pub/Sub DLQ topology, and one-delivery runtime coordination without an application retry loop. Stage 10C.2B.1 adds the local DLQ inspection subscription and clarifies that native Pub/Sub dead-letter forwarding is best effort rather than an exact delivery-attempt guarantee.

Provider data is not persisted to RAW or CORE. Production Pub/Sub IaC, production DLQ IAM, DLQ consumption/replay, long-running worker runtime, automatic ack-deadline extension, physical BigQuery external-event tables, warehouse loading, transformations, revision-aware CORE persistence, and risk scoring remain deferred.
