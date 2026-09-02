output "artifact_registry_repository_name" {
  description = "Artifact Registry repository name for application images."
  value       = google_artifact_registry_repository.application.name
}

output "cloud_run_service_name" {
  description = "Cloud Run service name when application deployment is enabled."
  value       = var.enable_cloud_run_service ? module.streamlit_service[0].service_name : null
}

output "runtime_service_account_email" {
  description = "Dedicated runtime service account email."
  value       = google_service_account.runtime.email
}

output "canonical_events_topic_name" {
  description = "Canonical events topic name."
  value       = var.enable_pubsub_topology ? module.pubsub_topology[0].canonical_events_topic_name : null
}

output "processing_subscription_name" {
  description = "Canonical event processing subscription name."
  value       = var.enable_pubsub_topology ? module.pubsub_topology[0].processing_subscription_name : null
}

output "dead_letter_topic_name" {
  description = "Dead-letter topic name."
  value       = var.enable_pubsub_topology ? module.pubsub_topology[0].dead_letter_topic_name : null
}

output "dead_letter_inspection_subscription_name" {
  description = "Dead-letter inspection subscription name."
  value       = var.enable_pubsub_topology ? module.pubsub_topology[0].dead_letter_inspection_subscription_name : null
}

output "gemini_secret_id" {
  description = "Gemini API key secret container ID. No secret value is output."
  value       = var.enable_agent_runtime ? google_secret_manager_secret.gemini_api_key[0].secret_id : null
}

output "agent_postgres_dsn_secret_id" {
  description = "Agent PostgreSQL DSN secret container ID. No secret value is output."
  value       = var.enable_agent_runtime ? google_secret_manager_secret.agent_postgres_dsn[0].secret_id : null
}

output "cloud_sql_connection_name" {
  description = "Cloud SQL connection name when managed PostgreSQL is enabled."
  value       = var.enable_managed_postgres ? google_sql_database_instance.agent[0].connection_name : null
}
