output "state_bucket_name" {
  description = "Production OpenTofu remote-state bucket name."
  value       = google_storage_bucket.production_state.name
}

output "workload_identity_provider_name" {
  description = "Full Workload Identity Provider resource name for GitHub Actions auth."
  value       = google_iam_workload_identity_pool_provider.github.name
}

output "deployer_service_account_email" {
  description = "Deployment service account email for production planning and future deployment workflows."
  value       = google_service_account.deployer.email
}
