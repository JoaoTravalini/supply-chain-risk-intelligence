variable "runtime_project_id" {
  description = "Production runtime GCP project ID. This may differ from the data project."
  type        = string
  default     = "REPLACE_WITH_RUNTIME_PROJECT_ID"
}

variable "data_project_id" {
  description = "GCP project containing approved CORE/MART analytical data."
  type        = string
  default     = "REPLACE_WITH_DATA_PROJECT_ID"
}

variable "region" {
  description = "Primary production region."
  type        = string
  default     = "us-central1"
}

variable "environment" {
  description = "Deployment environment label."
  type        = string
  default     = "production"
}

variable "service_name" {
  description = "Cloud Run service name."
  type        = string
  default     = "supplychain-sentinel"
}

variable "container_image" {
  description = "Immutable container image reference. Use a commit tag or digest; do not use latest."
  type        = string
  default     = "REPLACE_WITH_IMMUTABLE_IMAGE_REFERENCE"

  validation {
    condition     = var.container_image != "latest" && !endswith(var.container_image, ":latest")
    error_message = "container_image must not use the mutable latest tag."
  }
}

variable "enable_cloud_run_service" {
  description = "Gate for application deployment. Keep false until image and secret prerequisites exist."
  type        = bool
  default     = false
}

variable "allow_unauthenticated" {
  description = "Whether to grant allUsers Cloud Run invoker access. Safe default is false."
  type        = bool
  default     = false
}

variable "cloud_run_cpu" {
  description = "Cloud Run CPU limit."
  type        = string
  default     = "1"
}

variable "cloud_run_memory" {
  description = "Cloud Run memory limit."
  type        = string
  default     = "1Gi"
}

variable "cloud_run_min_instances" {
  description = "Minimum Cloud Run instances. Default zero avoids idle runtime cost."
  type        = number
  default     = 0
}

variable "cloud_run_max_instances" {
  description = "Maximum Cloud Run instances."
  type        = number
  default     = 3
}

variable "bigquery_core_dataset_id" {
  description = "Approved CORE dataset ID. Runtime receives read access here."
  type        = string
  default     = "supplychain_core"
}

variable "bigquery_mart_dataset_id" {
  description = "Approved MART dataset ID. Runtime receives read access here."
  type        = string
  default     = "supplychain_mart"
}

variable "gemini_model" {
  description = "Configured Gemini model name. Provider capability validation remains a separate gate."
  type        = string
  default     = "gemini-2.5-flash"
}

variable "agent_bigquery_max_bytes_billed" {
  description = "Application BigQuery read budget per guarded query."
  type        = number
  default     = 104857600
}

variable "enable_managed_postgres" {
  description = "Gate for billable managed PostgreSQL. Keep false until human cost approval."
  type        = bool
  default     = false
}

variable "postgres_tier" {
  description = "Cloud SQL machine tier used only when enable_managed_postgres is true."
  type        = string
  default     = "db-f1-micro"
}

variable "postgres_database_version" {
  description = "Managed PostgreSQL version."
  type        = string
  default     = "POSTGRES_17"
}

variable "postgres_availability_type" {
  description = "Cloud SQL availability type. ZONAL is the conservative portfolio default."
  type        = string
  default     = "ZONAL"
}

variable "pubsub_ack_deadline_seconds" {
  description = "Canonical processing subscription ack deadline."
  type        = number
  default     = 60
}

variable "pubsub_max_delivery_attempts" {
  description = "Bounded delivery attempts before dead-letter routing."
  type        = number
  default     = 5
}
