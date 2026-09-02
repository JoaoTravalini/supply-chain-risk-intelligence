resource "google_cloud_run_v2_service" "streamlit" {
  project  = var.project_id
  location = var.region
  name     = var.service_name

  deletion_protection = true
  ingress             = "INGRESS_TRAFFIC_INTERNAL_LOAD_BALANCER"
  labels              = var.labels

  template {
    service_account = var.runtime_service_account_email

    scaling {
      min_instance_count = var.min_instances
      max_instance_count = var.max_instances
    }

    containers {
      image = var.container_image

      ports {
        container_port = 8080
      }

      resources {
        limits = {
          cpu    = var.cpu
          memory = var.memory
        }
      }

      startup_probe {
        period_seconds    = 10
        timeout_seconds   = 5
        failure_threshold = 12

        http_get {
          path = "/_stcore/health"
          port = 8080
        }
      }

      liveness_probe {
        period_seconds    = 30
        timeout_seconds   = 5
        failure_threshold = 3

        http_get {
          path = "/_stcore/health"
          port = 8080
        }
      }

      dynamic "env" {
        for_each = var.environment_variables

        content {
          name  = env.key
          value = env.value
        }
      }

      dynamic "env" {
        for_each = var.secret_environment_variables

        content {
          name = env.key

          value_source {
            secret_key_ref {
              secret  = env.value.secret
              version = env.value.version
            }
          }
        }
      }

      dynamic "volume_mounts" {
        for_each = length(var.cloud_sql_instances) > 0 ? [1] : []

        content {
          name       = "cloudsql"
          mount_path = "/cloudsql"
        }
      }
    }

    dynamic "volumes" {
      for_each = length(var.cloud_sql_instances) > 0 ? [1] : []

      content {
        name = "cloudsql"

        cloud_sql_instance {
          instances = var.cloud_sql_instances
        }
      }
    }
  }
}
