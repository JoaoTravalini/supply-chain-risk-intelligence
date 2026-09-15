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
   - 19A. CI/CD + Containerization + Production IaC Preparation
   - 19B. Controlled Cloud Bootstrap + Deployment
20. Final Integration + Audit

## Current Stage

Stage 20 final integration and audit is in progress. Stages 0-18 established the architecture, contracts, data platform, deterministic risk engine, event processing semantics, LangGraph investigation workflow, validation/HITL, deterministic agent evaluations, Streamlit application, and vendor-neutral observability. Stage 19A added cloud-independent CI, credential-free OpenTofu validation, a non-root Cloud Run-compatible Streamlit container, a manual plan-only production workflow, and separate bootstrap/production OpenTofu roots. Stage 19B applied the controlled production bootstrap and dashboard-first foundation, built and pushed an immutable Streamlit image, and deployed the private Cloud Run dashboard.

Current production is dashboard-first: Risk Portfolio and Supplier Explorer are deployed on Cloud Run in `sc-sentinel-prod-7h2k9q`, use authenticated access only, retain `allow_unauthenticated=false`, use `INGRESS_TRAFFIC_ALL` for authenticated `run.app` access, run with min instances `0`, bounded max instances, and request-based CPU allocation, and read CORE/MART BigQuery data from `supplychain-sentinel-646511` without RAW access. Runtime BigQuery jobs execute in the runtime project while table references remain fully qualified to the data project.

Implemented but production-gated capabilities include production Pub/Sub topology, managed PostgreSQL, Gemini runtime secrets, AI Investigation/HITL production runtime, production scheduling, DLQ replay operations, and remote telemetry exporters. The Stage 15 Gemini workflow remains implemented and offline-validated, but live Gemini provider validation must be repeated once the external provider/key capability blocker is restored. Live weather and seismic scores depend on qualifying CORE evidence.
