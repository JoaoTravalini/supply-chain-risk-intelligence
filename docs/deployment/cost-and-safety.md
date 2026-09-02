# Cost and Safety Boundary

Stage 19A is preparation only. It performs no cloud mutations and creates
no billable resources.

## Billable Resource Categories Modeled

The production OpenTofu design models resources that may incur cost after
future approved apply:

- Cloud SQL for PostgreSQL, if `enable_managed_postgres=true`;
- Cloud Run request/runtime usage;
- Artifact Registry image storage and network transfer;
- Pub/Sub message delivery and retention;
- BigQuery query processing in the data project;
- Secret Manager secret storage and access;
- GCS remote-state storage;
- future telemetry exporters or managed observability backends.

Stage 19A does not quote live pricing. Cost review belongs to the human
approval step before Stage 19B bootstrap/deployment.

## Conservative Defaults

The production root uses safety-first defaults:

- Cloud Run application deployment disabled;
- public access disabled;
- Cloud Run minimum instances set to zero;
- finite maximum instances;
- managed PostgreSQL disabled;
- Cloud SQL deletion protection enabled when created;
- Cloud SQL Admin API enabled only when managed PostgreSQL is explicitly
  enabled;
- no secret versions or values in OpenTofu;
- no RAW BigQuery access for the runtime identity.

The dashboard-first initial deployment does not require Cloud SQL or the
Cloud SQL Admin API. Persistent LangGraph investigation and HITL
production capability remains deferred until managed PostgreSQL is
approved.

## Billing Boundary

The current development project was intentionally operated without
billing. Stage 19A does not attach a Billing Account, enable a trial, or
alter billing settings.

Any resource requiring billing remains unapplied until an explicit later
decision.

## Data and Secret Safety

Production design keeps these values out of Git and container layers:

- API keys;
- service-account JSON keys;
- DSNs and database passwords;
- Secret Manager secret versions;
- provider request/response payloads.

Runtime secrets are injected later through managed runtime configuration.
