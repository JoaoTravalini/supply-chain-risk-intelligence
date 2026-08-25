# Infrastructure

This directory contains the OpenTofu root module for SupplyChain Sentinel.

Stage 4 establishes only the Infrastructure as Code foundation. It provisions zero Google Cloud resources.

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

Credentials, service-account key paths, billing accounts, regions, and zones are not configured in Stage 4.

## Variables

Create a local `terraform.tfvars` from the example when local validation requires a project value:

```bash
cp terraform.tfvars.example terraform.tfvars
```

Use a real project ID only in local, ignored files. Do not commit developer-specific project IDs, credentials, billing identifiers, or secrets.

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
