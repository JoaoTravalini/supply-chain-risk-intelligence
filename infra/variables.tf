variable "project_id" {
  description = "Google Cloud project ID used by the infrastructure root module."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a syntactically valid Google Cloud project ID: 6 to 30 lowercase letters, digits, or hyphens; start with a letter; and end with a letter or digit."
  }
}

variable "bigquery_location" {
  description = "BigQuery dataset location for billing-free development. Defaults to US for synthetic, non-sensitive portfolio data; production must review residency, co-location, latency, and organizational requirements."
  type        = string
  default     = "US"

  validation {
    condition     = can(regex("^[A-Za-z0-9-]+$", var.bigquery_location))
    error_message = "bigquery_location must be a valid BigQuery location identifier such as US, EU, or a supported regional location."
  }
}
