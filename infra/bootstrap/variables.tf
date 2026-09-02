variable "bootstrap_project_id" {
  description = "GCP project that will own one-time production bootstrap resources."
  type        = string

  validation {
    condition     = length(trimspace(var.bootstrap_project_id)) > 0
    error_message = "bootstrap_project_id must not be blank."
  }
}

variable "region" {
  description = "Region for regional bootstrap resources."
  type        = string
  default     = "us-central1"
}

variable "state_bucket_name" {
  description = "Globally unique GCS bucket name for production OpenTofu remote state."
  type        = string

  validation {
    condition     = length(trimspace(var.state_bucket_name)) > 0
    error_message = "state_bucket_name must not be blank."
  }
}

variable "github_repository" {
  description = "GitHub repository allowed to impersonate the deployer service account, in owner/name form."
  type        = string

  validation {
    condition     = can(regex("^[A-Za-z0-9_.-]+/[A-Za-z0-9_.-]+$", var.github_repository))
    error_message = "github_repository must be in owner/name form."
  }
}

variable "github_owner" {
  description = "GitHub organization or user that owns the repository."
  type        = string

  validation {
    condition     = length(trimspace(var.github_owner)) > 0
    error_message = "github_owner must not be blank."
  }
}

variable "github_production_environment" {
  description = "GitHub Environment expected to protect production plan/apply jobs."
  type        = string
  default     = "production"
}

variable "deployer_service_account_id" {
  description = "Account ID for the production deployment service account."
  type        = string
  default     = "supplychain-production-deployer"
}

variable "workload_identity_pool_id" {
  description = "Workload Identity Pool ID for GitHub Actions OIDC."
  type        = string
  default     = "github-actions-production"
}

variable "workload_identity_provider_id" {
  description = "Workload Identity Provider ID for GitHub Actions OIDC."
  type        = string
  default     = "github-actions-oidc"
}
