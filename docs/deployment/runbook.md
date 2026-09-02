# Production Deployment Runbook

This runbook documents the intended Stage 19B flow. Do not execute these
steps until cloud bootstrap/deployment is explicitly approved.

## Preconditions

- Billing decision reviewed and approved.
- Production runtime project chosen.
- Data project chosen separately from the runtime project.
- GitHub repository and `production` Environment protections configured.
- Human approval obtained for bootstrap and any billable resources.
- Gemini provider/key capability blocker resolved or accepted as a known
  limitation.

## Phase 1: Bootstrap

Bootstrap creates privileged prerequisites such as the remote-state
bucket and GitHub Workload Identity Federation.
It is also the single OpenTofu owner for platform API enablements needed
by state, IAM, and Workload Identity Federation. Do not duplicate those
API resources in the production root.

```shell
cd infra/bootstrap
tofu init
tofu plan -out=bootstrap.tfplan
```

The saved plan must be reviewed before any apply. Stage 19A does not run
this apply.

After approved bootstrap, configure the production workflow repository
variables:

- `PRODUCTION_WIF_PROVIDER`
- `PRODUCTION_DEPLOYER_SERVICE_ACCOUNT`
- `PRODUCTION_TOFU_STATE_BUCKET`

## Phase 2: Production Plan

The production plan workflow is manual and plan-only. It uses GitHub OIDC
to impersonate the deployment service account. It must never fall back to
a service-account JSON key.

The workflow receives explicit runtime/data project IDs, region, and an
immutable image reference. It runs `tofu plan`; it does not run
`tofu apply`.
Production state owns application-specific service enablements only; APIs
already managed by bootstrap remain bootstrap-owned and enabled.

The first production foundation is dashboard-first: Risk Portfolio and
Supplier Explorer over guarded CORE/MART BigQuery reads. Keep
`enable_pubsub_topology=false`, `enable_agent_runtime=false`, and
`enable_managed_postgres=false` until event processing, AI
investigation/HITL, and managed PostgreSQL are separately reviewed.

## Phase 3: Secret Seeding

Secret Manager secret containers are modeled by OpenTofu, but secret
versions are seeded outside Git through a controlled human-approved
process.

Never place secret values in:

- `.tfvars`;
- GitHub workflow YAML;
- Docker build arguments;
- Docker layers;
- repository documentation;
- OpenTofu source.

Secrets can be rotated by adding new Secret Manager versions without
rebuilding the image.

## Phase 4: Application Deployment

Build and push an immutable image only after explicit approval. The
runtime service account reads CORE/MART data. Pub/Sub, exact secrets,
and PostgreSQL are added only when their production feature gates are
enabled. It does not receive RAW BigQuery access.

Cloud Run public access remains disabled unless
`allow_unauthenticated=true` is explicitly reviewed and approved.

## Rollback

Application rollback deploys a previously reviewed immutable image
revision. Infrastructure rollback is handled through reviewed OpenTofu
plans. Do not blindly revert state. Destructive database rollback is out
of scope.

## Safety Notes

Normal CI is cloud-independent. The development OpenTofu root remains a
separate state boundary and must not be migrated into production modules.
Production bootstrap and deployment remain Stage 19B work.
