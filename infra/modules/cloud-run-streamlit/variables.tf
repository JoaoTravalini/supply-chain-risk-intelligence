variable "project_id" {
  description = "Project that owns the Cloud Run service."
  type        = string
}

variable "region" {
  description = "Cloud Run region."
  type        = string
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
}

variable "container_image" {
  description = "Immutable container image reference, preferably pinned by digest."
  type        = string
}

variable "runtime_service_account_email" {
  description = "Dedicated runtime service account for the Streamlit application."
  type        = string
}

variable "labels" {
  description = "Low-cardinality labels applied to supported resources."
  type        = map(string)
  default     = {}
}

variable "environment_variables" {
  description = "Non-secret runtime environment variables."
  type        = map(string)
  default     = {}
}

variable "secret_environment_variables" {
  description = "Secret Manager environment variable mappings. Secret versions are seeded separately."
  type = map(object({
    secret  = string
    version = string
  }))
  default = {}
}

variable "cloud_sql_instances" {
  description = "Optional Cloud SQL connection names."
  type        = list(string)
  default     = []
}

variable "cpu" {
  description = "Cloud Run CPU limit."
  type        = string
  default     = "1"
}

variable "memory" {
  description = "Cloud Run memory limit."
  type        = string
  default     = "1Gi"
}

variable "min_instances" {
  description = "Minimum Cloud Run instances."
  type        = number
  default     = 0
}

variable "max_instances" {
  description = "Maximum Cloud Run instances."
  type        = number
  default     = 3
}
