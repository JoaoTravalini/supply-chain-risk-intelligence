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
11. BigQuery RAW/CORE Data Pipeline
12. Deterministic Risk Engine & MART

## Agentic AI

13. LangGraph State + Persistence
14. Guarded BigQuery Read Tools + SQL Security + Cost Guardrails
15. LangGraph Evidence Investigation Workflow
16. Validation + Human-in-the-loop + Agent Evaluations

## Product & Production

17. Streamlit Application
18. Production-Grade Observability
19. CI/CD + Production IaC + Deployment

## Current Stage

Stage 18 implementation is complete. Stage 10A adds pure processing decision semantics, deterministic source-content fingerprints, a minimal prior-record value object, and local classifier behavior for `NEW`, `DUPLICATE`, and `REVISION_CANDIDATE`. Stage 10B adds the local persistent processing ledger, schema version 1, revision-marker extraction for USGS seismic events, and ledger-aware `NEW`, `DUPLICATE`, `NEWER_REVISION`, `STALE_REVISION`, and `REVISION_CONFLICT` resolution. Stage 10C adds safe processing coordination, failure classification, bounded redelivery/dead-letter disposition policy, native local Pub/Sub DLQ topology, and the local DLQ inspection subscription. Stage 11 defines and deploys `supplychain_raw.canonical_events`, the `supplychain_core.canonical_events` view, `supplychain_core.suppliers`, and the batch-load warehouse runtime boundary. Stage 12 implements Supplier Risk Model v1, CORE risk input reading, MART current/history loaders, and deployed OpenTofu-managed `supplier_risk_current` and `supplier_risk_history` tables. Stage 13 adds a minimal real LangGraph investigation graph, explicit investigation/thread identity, typed serializable investigation state, an InvestigationService boundary, official PostgreSQL checkpoint persistence, local Docker Compose PostgreSQL configuration, and explicit checkpoint setup/smoke commands. Stage 14 adds a guarded read-only BigQuery agent data service with static SQL, typed inputs/outputs, dry-run cost checks, maximum bytes billed, finite timeouts, and bounded result sizes. Stage 15 adds the bounded LangGraph investigation workflow, Gemini provider abstraction, versioned prompt, structured report contract, evidence citation validation, zero-evidence semantics, and `COMPLETED` checkpoint persistence. Stage 16 adds deterministic report validation, separate human-review lifecycle state, native LangGraph interrupt/resume review, approve/reject review decisions, checkpointed review audit metadata, and an offline deterministic agent evaluation command. Stage 17 adds the Streamlit application with Risk Portfolio, Supplier Explorer, and AI Investigation/HITL pages backed by typed services. Stage 18 adds vendor-neutral OpenTelemetry traces and metrics, structured JSON logs, context-local correlation identifiers, safe diagnostics, and data-minimizing instrumentation across BigQuery, processing, Pub/Sub, investigation, model, validation, HITL, and Streamlit action boundaries.

The human-approved Stage 11 OpenTofu plan was applied with three BigQuery objects added and no destroys. The Supplier snapshot was loaded for validation, and one synthetic Canonical Event RAW/CORE smoke validated the batch-load handler path. The human-approved Stage 12 OpenTofu plan was applied with two MART BigQuery objects added and no destroys. One full 120-Supplier development assessment batch validated the deterministic risk engine and MART load-job path. Stage 13 validates durable local LangGraph checkpoint semantics independently from LLMs. Stage 14 validates guarded read-only BigQuery retrieval through the approved service boundary. Stage 15 validates the bounded investigation workflow with offline fakes by default. Its full integration path reached the Gemini boundary through BigQuery/LangGraph/PostgreSQL, and an independent minimal text-only Gemini diagnostic reproduced the external provider/key capability blocker without Supplier or project context. Stage 16 validates report integrity and HITL routing offline and provides `uv run python -m supplychain.agent.evaluation` as the deterministic evaluation gate. Stage 17 validates the Streamlit presentation layer offline with deterministic fakes and AppTest, while preserving explicit investigation execution and safe provider-failure display. Stage 18 validates telemetry locally with in-memory OpenTelemetry test exporters and no remote exporter. Follow-up: repeat live Gemini provider validation once provider/key capability is restored. Live weather and seismic scores depend on qualifying CORE evidence; the current validation batch had no qualifying weather or seismic CORE events. CI/CD, production IAM, production deployment, production scheduling, managed production PostgreSQL, and telemetry exporter deployment remain deferred to Stage 19 or later.
