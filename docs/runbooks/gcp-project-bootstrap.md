# GCP Project Bootstrap Runbook

This runbook documents the manual, billing-free Google Cloud project bootstrap for SupplyChain Sentinel.

Stage 3 validates only the existing Google Cloud project state. It does not create infrastructure, link billing, enable paid services, modify IAM, or configure application resources.

## Requirements

- Google Cloud CLI installed locally.
- A developer-authenticated Google Cloud CLI session.
- A dedicated gcloud configuration for this project.
- A dedicated Google Cloud project.
- No Cloud Billing Account linked to the project during the billing-free development phase.

## Configuration Convention

Use a dedicated gcloud configuration:

```bash
gcloud config configurations activate supplychain-sentinel
```

Use a project ID chosen manually by the developer:

```bash
gcloud config set project PROJECT_ID
```

`PROJECT_ID` is not a secret, but application code and portable repository configuration should not be unnecessarily coupled to a developer-specific project.

## Inspect Active Account

Verify that an account is active:

```bash
gcloud auth list --filter="status:ACTIVE"
```

Do not commit account emails, access tokens, refresh tokens, Application Default Credentials, or gcloud credential files to the repository.

## Inspect Active Configuration

Verify the active gcloud configuration:

```bash
gcloud config configurations list
```

Expected active configuration:

```text
supplychain-sentinel
```

## Inspect Active Project

Verify the configured project:

```bash
gcloud config get-value project
```

Then verify that the project exists:

```bash
gcloud projects describe PROJECT_ID
```

## Verify Project Lifecycle

Verify that the project lifecycle state is active:

```bash
gcloud projects describe PROJECT_ID --format="value(lifecycleState)"
```

Expected result:

```text
ACTIVE
```

## Verify Billing Status

Verify billing state:

```bash
gcloud beta billing projects describe PROJECT_ID
```

During the current development phase, the expected result is logically equivalent to:

```yaml
billingAccountName: ''
billingEnabled: false
```

This is intentional. No Cloud Billing Account should be linked during billing-free development.

Do not document or commit a real Cloud Billing Account ID.

## Expected Billing-Free State

The expected Stage 3 state is:

- The project exists.
- The project lifecycle state is `ACTIVE`.
- Billing is disabled.
- No Cloud Billing Account is associated with the project.
- No BigQuery datasets, Pub/Sub topics, Cloud Run services, Cloud Scheduler jobs, service accounts, IAM changes, or Secret Manager resources are created by this stage.

## Development Strategy

Initial development uses billing-free or local paths:

- BigQuery analytical development will use BigQuery Sandbox when introduced.
- Pub/Sub development will use the local Google Cloud Pub/Sub emulator before any managed Pub/Sub deployment.
- Python application services will run locally during development.
- Streamlit will run locally during development.
- LangGraph will run locally during development.
- PostgreSQL will use a local or explicitly free-tier development option when that stage arrives.
- Cloud Run and other managed deployment infrastructure remain deferred until a later deployment decision.

## Development and Deployment Separation

Local and billing-free development flow:

```text
External data
-> local application
-> local Pub/Sub emulator when introduced
-> BigQuery Sandbox when introduced
-> local agent
-> local Streamlit
```

Future cloud deployment may introduce managed Pub/Sub, Cloud Run, managed cloud integrations, and other deployment resources. That remains a separate decision and is not approved by this runbook.

Domain and business logic should be designed so local emulators and adapters can later be replaced by managed cloud adapters without rewriting domain logic.

## Cost-Safety Rule

No Cloud Billing Account will be linked during the billing-free development phase.

A future decision to enable billing requires:

- Explicit developer approval.
- Review of service pricing.
- Review of security controls.
- Review of service quotas and limits.
- Review of exposure to unintended charges.

Cloud Billing budgets can help monitor or alert on spend, but they should not be treated as hard spending caps.

## Security Considerations

- Do not commit OAuth tokens, refresh tokens, Application Default Credentials, service-account keys, gcloud user credentials, account emails, payment information, or Cloud Billing Account identifiers.
- Keep gcloud configuration and credential directories outside the repository.
- Use least-privilege IAM when future stages introduce cloud resources.
- Do not use service-account key files unless a later ADR explicitly approves that exception.
- Do not link billing or enable paid services during billing-free development.

## Teardown

If the dedicated project must be removed, inspect it first:

```bash
gcloud projects describe PROJECT_ID
```

Delete the project only after confirming it is the intended dedicated project:

```bash
gcloud projects delete PROJECT_ID
```

Project deletion is a destructive operation. It should be performed manually by the developer, not by repository automation.
