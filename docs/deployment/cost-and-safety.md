# Cost and Safety Boundary

The project uses a separate production runtime project for approved
Cloud Run dashboard resources while preserving the development/data
project as billing-disabled. Production is cost-controlled rather than
claimed to be free.

## Billable Resource Categories Modeled

The production OpenTofu design models resources that may incur cost after
future approved apply:

- Cloud SQL for PostgreSQL, if `enable_managed_postgres=true`;
- Cloud Run request/runtime usage;
- Artifact Registry image storage and network transfer;
- Pub/Sub message delivery and retention;
- BigQuery query processing in the runtime/job project while reading
  approved CORE/MART datasets in the data project;
- Secret Manager secret storage and access;
- GCS remote-state storage;
- future telemetry exporters or managed observability backends.

This document does not quote live pricing. Cost review belongs to human
approval before enabling additional production resources.

## Conservative Defaults

The production root uses safety-first defaults:

- Cloud Run application deployment disabled;
- public access disabled;
- Cloud Run minimum instances set to zero;
- Cloud Run request-based billing with CPU idle enabled for the
  dashboard-first service;
- finite maximum instances;
- production Pub/Sub topology disabled;
- production agent/HITL runtime infrastructure disabled;
- managed PostgreSQL disabled;
- Cloud SQL deletion protection enabled when created;
- Cloud SQL Admin API enabled only when managed PostgreSQL is explicitly
  enabled;
- no secret versions or values in OpenTofu;
- no RAW BigQuery access for the runtime identity.

The dashboard-first initial deployment supports Risk Portfolio and
Supplier Explorer over guarded CORE/MART BigQuery reads. It does not
require Pub/Sub, Gemini secrets, PostgreSQL DSN secrets, Cloud SQL, or
the Cloud SQL Admin API. Persistent LangGraph investigation and HITL
production capability remains deferred until agent runtime and
PostgreSQL decisions are explicitly approved.

The reviewed dashboard production deployment enables Cloud Run for the
Streamlit service while retaining private IAM, minimum instances `0`,
bounded maximum instances, request-based CPU allocation, and disabled
agent runtime, Pub/Sub topology, and managed PostgreSQL.

## Billing Boundary

The data/development project remains billing-disabled. The runtime
project is the only production project linked to billing for approved
runtime resources. Additional billable services remain gated until
explicit review.

## Data and Secret Safety

Production design keeps these values out of Git and container layers:

- API keys;
- service-account JSON keys;
- DSNs and database passwords;
- Secret Manager secret versions;
- provider request/response payloads.

Runtime secrets are injected later through managed runtime configuration.
