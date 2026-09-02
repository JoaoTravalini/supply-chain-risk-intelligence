locals {
  common_labels = {
    application = "supplychain-sentinel"
    environment = var.environment
    managed_by  = "opentofu"
  }

  base_production_services = [
    "artifactregistry.googleapis.com",
    "bigquery.googleapis.com",
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "run.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
  ]

  pubsub_services = var.enable_pubsub_topology ? [
    "pubsub.googleapis.com",
  ] : []

  agent_runtime_services = var.enable_agent_runtime ? [
    "secretmanager.googleapis.com",
  ] : []

  managed_postgres_services = var.enable_managed_postgres ? [
    "sqladmin.googleapis.com",
  ] : []

  production_services = toset(concat(
    local.base_production_services,
    local.pubsub_services,
    local.agent_runtime_services,
    local.managed_postgres_services,
  ))

  non_secret_environment = {
    SUPPLYCHAIN_GCP_PROJECT_ID                  = var.data_project_id
    SUPPLYCHAIN_ENVIRONMENT                     = var.environment
    SUPPLYCHAIN_SERVICE_NAME                    = var.service_name
    SUPPLYCHAIN_AGENT_BIGQUERY_MAX_BYTES_BILLED = tostring(var.agent_bigquery_max_bytes_billed)
  }

  agent_non_secret_environment = var.enable_agent_runtime ? {
    SUPPLYCHAIN_GEMINI_MODEL = var.gemini_model
  } : {}

  agent_secret_environment = var.enable_agent_runtime ? {
    GEMINI_API_KEY = {
      secret  = google_secret_manager_secret.gemini_api_key[0].secret_id
      version = "latest"
    }
    SUPPLYCHAIN_AGENT_POSTGRES_DSN = {
      secret  = google_secret_manager_secret.agent_postgres_dsn[0].secret_id
      version = "latest"
    }
  } : {}

  cloud_sql_instances = var.enable_managed_postgres ? [google_sql_database_instance.agent[0].connection_name] : []
}

resource "google_project_service" "production" {
  for_each = local.production_services

  project            = var.runtime_project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_artifact_registry_repository" "application" {
  project       = var.runtime_project_id
  location      = var.region
  repository_id = "supplychain-sentinel"
  description   = "SupplyChain Sentinel application container images."
  format        = "DOCKER"
  labels        = local.common_labels

  depends_on = [google_project_service.production]
}

resource "google_service_account" "runtime" {
  project      = var.runtime_project_id
  account_id   = "supplychain-sentinel-runtime"
  display_name = "SupplyChain Sentinel runtime"
  description  = "Dedicated runtime identity for the Cloud Run Streamlit application."
}

resource "google_secret_manager_secret" "gemini_api_key" {
  count = var.enable_agent_runtime ? 1 : 0

  project   = var.runtime_project_id
  secret_id = "supplychain-gemini-api-key"

  replication {
    auto {}
  }

  labels = local.common_labels
}

resource "google_secret_manager_secret" "agent_postgres_dsn" {
  count = var.enable_agent_runtime ? 1 : 0

  project   = var.runtime_project_id
  secret_id = "supplychain-agent-postgres-dsn"

  replication {
    auto {}
  }

  labels = local.common_labels
}

resource "google_sql_database_instance" "agent" {
  count = var.enable_managed_postgres ? 1 : 0

  project             = var.runtime_project_id
  name                = "supplychain-agent-postgres"
  region              = var.region
  database_version    = var.postgres_database_version
  deletion_protection = true

  settings {
    tier              = var.postgres_tier
    availability_type = var.postgres_availability_type
    disk_type         = "PD_SSD"
    disk_size         = 10

    backup_configuration {
      enabled                        = true
      point_in_time_recovery_enabled = true
    }

    ip_configuration {
      ipv4_enabled = false
    }

    user_labels = local.common_labels
  }
}

module "pubsub_topology" {
  count = var.enable_pubsub_topology ? 1 : 0

  source = "../../modules/pubsub-topology"

  project_id                    = var.runtime_project_id
  labels                        = local.common_labels
  runtime_service_account_email = google_service_account.runtime.email
  ack_deadline_seconds          = var.pubsub_ack_deadline_seconds
  max_delivery_attempts         = var.pubsub_max_delivery_attempts

  depends_on = [google_project_service.production]
}

resource "google_project_iam_member" "runtime_bigquery_job_user" {
  project = var.runtime_project_id
  role    = "roles/bigquery.jobUser"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_core_viewer" {
  project    = var.data_project_id
  dataset_id = var.bigquery_core_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_bigquery_dataset_iam_member" "runtime_mart_viewer" {
  project    = var.data_project_id
  dataset_id = var.bigquery_mart_dataset_id
  role       = "roles/bigquery.dataViewer"
  member     = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_gemini_secret_accessor" {
  count = var.enable_agent_runtime ? 1 : 0

  project   = var.runtime_project_id
  secret_id = google_secret_manager_secret.gemini_api_key[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_secret_manager_secret_iam_member" "runtime_postgres_secret_accessor" {
  count = var.enable_agent_runtime ? 1 : 0

  project   = var.runtime_project_id
  secret_id = google_secret_manager_secret.agent_postgres_dsn[0].secret_id
  role      = "roles/secretmanager.secretAccessor"
  member    = "serviceAccount:${google_service_account.runtime.email}"
}

resource "google_project_iam_member" "runtime_cloudsql_client" {
  count = var.enable_managed_postgres ? 1 : 0

  project = var.runtime_project_id
  role    = "roles/cloudsql.client"
  member  = "serviceAccount:${google_service_account.runtime.email}"
}

module "streamlit_service" {
  count = var.enable_cloud_run_service ? 1 : 0

  source = "../../modules/cloud-run-streamlit"

  project_id                    = var.runtime_project_id
  region                        = var.region
  service_name                  = var.service_name
  container_image               = var.container_image
  runtime_service_account_email = google_service_account.runtime.email
  labels                        = local.common_labels
  cpu                           = var.cloud_run_cpu
  memory                        = var.cloud_run_memory
  min_instances                 = var.cloud_run_min_instances
  max_instances                 = var.cloud_run_max_instances
  cloud_sql_instances           = local.cloud_sql_instances

  environment_variables        = merge(local.non_secret_environment, local.agent_non_secret_environment)
  secret_environment_variables = local.agent_secret_environment

  depends_on = [google_project_service.production]
}

resource "google_cloud_run_v2_service_iam_member" "public_invoker" {
  count = var.enable_cloud_run_service && var.allow_unauthenticated ? 1 : 0

  project  = var.runtime_project_id
  location = var.region
  name     = module.streamlit_service[0].service_name
  role     = "roles/run.invoker"
  member   = "allUsers"
}
