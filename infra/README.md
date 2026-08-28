# Infrastructure

This directory contains the OpenTofu root module for SupplyChain Sentinel.

Stage 5 defines the BigQuery analytical dataset architecture in OpenTofu and provisions the three development datasets in BigQuery Sandbox. Stage 11 defines the first RAW/CORE table and view resources. Applying those resources is intentionally gated on human review of the saved Stage 11 OpenTofu plan.

## Requirements

- OpenTofu 1.12.x.
- Access to the existing billing-free Google Cloud project when future non-local validation requires it.
- No Cloud Billing Account linked during the billing-free development phase.

## Provider Strategy

The root module declares the `hashicorp/google` provider with a major-version constraint:

```hcl
version = ">= 7.0, < 8.0"
```

The exact provider version and checksums are recorded in `.terraform.lock.hcl` after `tofu init`. The lock file is versioned and should not be manually edited.

The provider is configured only with:

```hcl
project = var.project_id
```

Credentials, service-account key paths, billing accounts, regions, and zones are not configured.

## BigQuery Datasets

The root module declares exactly three BigQuery datasets:

- `supplychain_raw`
- `supplychain_core`
- `supplychain_mart`

These datasets represent analytical boundaries. Stage 11 adds exactly these BigQuery objects:

- `supplychain_raw.canonical_events`: append-oriented Canonical Event v1 history table.
- `supplychain_core.canonical_events`: revision-safe current Canonical Event view over RAW.
- `supplychain_core.suppliers`: Supplier v1 master-data snapshot table.

No MART tables, routines, dataset access blocks, IAM bindings, external
connections, reservations, encryption resources, provider-specific RAW tables,
or production Pub/Sub resources are defined in Stage 11.

The datasets are managed by OpenTofu in BigQuery Sandbox during billing-free development. Sandbox validation does not cover production streaming behavior, because streaming is unavailable without billing.

BigQuery Sandbox enforces 60-day expiration for tables and partitions. The root module represents this development behavior explicitly with dataset-level `bigquery_sandbox_default_expiration_ms`; this is not a production retention policy. Stage 11 table resources do not hardcode absolute expiration timestamps and are expected to inherit the dataset default behavior. Future production deployment must redesign retention separately for RAW, CORE, and MART based on business, compliance, cost, and replay requirements.

Datasets are persistent analytical boundaries. The module deliberately does not set `delete_contents_on_destroy = true`; accidental infrastructure destroy operations must not silently delete future dataset contents. Stage 11 table resources set `deletion_protection = false` to stay consistent with the disposable billing-free Sandbox development environment; production deletion behavior must be reviewed separately.

## Variables

Create a local `terraform.tfvars` from the example when local validation requires a project value:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Use a real project ID only in local, ignored files. Do not commit developer-specific project IDs, credentials, billing identifiers, or secrets.

`bigquery_location` defaults to `US` for synthetic, non-sensitive portfolio development data. Future production deployment must review residency, service co-location, latency, and organizational requirements.

`bigquery_sandbox_default_expiration_ms` defaults to `5184000000`, representing BigQuery Sandbox's 60-day table and partition expiration in the billing-free development project. Production retention requirements are intentionally deferred.

## State Strategy

No remote backend is configured in Stage 4.

If local state is ever created during billing-free development, it is temporary and must not be committed. OpenTofu state may contain sensitive information.

A remote backend with locking and access control must be evaluated before shared or production infrastructure is introduced. Remote-state migration is deferred.

## Security Rules

- Do not commit state files, plan files, credentials, real tfvars files, service-account keys, access tokens, Application Default Credentials, billing identifiers, or account emails.
- Do not link billing from this module.
- Do not configure credentials in provider blocks.
- Review plans before any future apply.
- `tofu apply` is not a local validation command.

## Canonical Validation Commands

From this directory:

```bash
tofu version
tofu fmt -recursive
tofu fmt -check -recursive
tofu init
tofu validate
tofu providers
```

These commands are non-mutating with respect to cloud resources. `tofu init` may create local `.terraform/` files and `.terraform.lock.hcl`; `.terraform/` is ignored and `.terraform.lock.hcl` is versioned.

Do not run `tofu apply` as a validation command. Future applies require explicit human review of the exact saved plan to be applied.
