locals {
  common_labels = {
    application = "supplychain-sentinel"
    environment = "production"
    managed_by  = "opentofu"
  }

  bootstrap_services = toset([
    "iam.googleapis.com",
    "iamcredentials.googleapis.com",
    "serviceusage.googleapis.com",
    "sts.googleapis.com",
    "storage.googleapis.com",
  ])
}

resource "google_project_service" "bootstrap" {
  for_each = local.bootstrap_services

  project            = var.bootstrap_project_id
  service            = each.value
  disable_on_destroy = false
}

resource "google_storage_bucket" "production_state" {
  name                        = var.state_bucket_name
  project                     = var.bootstrap_project_id
  location                    = var.region
  uniform_bucket_level_access = true
  public_access_prevention    = "enforced"
  force_destroy               = false

  versioning {
    enabled = true
  }

  labels = local.common_labels
}

resource "google_service_account" "deployer" {
  project      = var.bootstrap_project_id
  account_id   = var.deployer_service_account_id
  display_name = "SupplyChain Sentinel production deployer"
  description  = "GitHub Actions OIDC impersonation identity for reviewed production plans and future deployments."
}

resource "google_iam_workload_identity_pool" "github" {
  project                   = var.bootstrap_project_id
  workload_identity_pool_id = var.workload_identity_pool_id
  display_name              = "GitHub Actions Production"
  description               = "OIDC trust boundary for reviewed SupplyChain Sentinel production workflows."
}

resource "google_iam_workload_identity_pool_provider" "github" {
  project                            = var.bootstrap_project_id
  workload_identity_pool_id          = google_iam_workload_identity_pool.github.workload_identity_pool_id
  workload_identity_pool_provider_id = var.workload_identity_provider_id
  display_name                       = "GitHub Actions OIDC"
  description                        = "Restricts production deployer impersonation to the configured GitHub repository and environment."

  attribute_mapping = {
    "google.subject"             = "assertion.sub"
    "attribute.actor"            = "assertion.actor"
    "attribute.repository"       = "assertion.repository"
    "attribute.repository_owner" = "assertion.repository_owner"
    "attribute.ref"              = "assertion.ref"
    "attribute.environment"      = "assertion.environment"
  }

  attribute_condition = join(" && ", [
    "assertion.repository == '${var.github_repository}'",
    "assertion.repository_owner == '${var.github_owner}'",
    "assertion.environment == '${var.github_production_environment}'",
  ])

  oidc {
    issuer_uri = "https://token.actions.githubusercontent.com"
  }
}

resource "google_service_account_iam_member" "github_wif_user" {
  service_account_id = google_service_account.deployer.name
  role               = "roles/iam.workloadIdentityUser"
  member             = "principalSet://iam.googleapis.com/${google_iam_workload_identity_pool.github.name}/attribute.repository/${var.github_repository}"
}

resource "google_storage_bucket_iam_member" "deployer_state_access" {
  bucket = google_storage_bucket.production_state.name
  role   = "roles/storage.objectAdmin"
  member = "serviceAccount:${google_service_account.deployer.email}"
}

resource "google_project_iam_member" "deployer_roles" {
  for_each = toset([
    "roles/artifactregistry.admin",
    "roles/iam.serviceAccountAdmin",
    "roles/iam.serviceAccountUser",
    "roles/pubsub.admin",
    "roles/run.admin",
    "roles/secretmanager.admin",
    "roles/serviceusage.serviceUsageAdmin",
  ])

  project = var.bootstrap_project_id
  role    = each.value
  member  = "serviceAccount:${google_service_account.deployer.email}"
}
