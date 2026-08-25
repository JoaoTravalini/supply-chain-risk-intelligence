# ADR 0001: GCP as Primary Cloud Platform

## Status

Accepted

## Context

SupplyChain Sentinel needs a cloud-native architecture for ingestion, messaging, analytical storage, scheduled workloads, managed identity, secrets, and deployment. The project should demonstrate enterprise-style cloud engineering while remaining suitable for a constrained portfolio deployment.

## Decision

Google Cloud Platform is the primary cloud platform for the project.

Target GCP services include Cloud Run, Pub/Sub, BigQuery, Cloud Scheduler, Google Secret Manager, and Workload Identity Federation.

## Consequences

- Future implementation will align infrastructure, deployment, IAM, and observability patterns around GCP.
- Cloud-specific code must remain behind adapters or infrastructure boundaries so domain logic is not coupled to provider SDKs.
- GCP usage must be designed with least privilege and cost controls from the beginning.
- Changing the primary cloud platform requires a new ADR.
