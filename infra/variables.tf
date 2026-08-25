variable "project_id" {
  description = "Google Cloud project ID used by the infrastructure root module."
  type        = string

  validation {
    condition     = can(regex("^[a-z][a-z0-9-]{4,28}[a-z0-9]$", var.project_id))
    error_message = "project_id must be a syntactically valid Google Cloud project ID: 6 to 30 lowercase letters, digits, or hyphens; start with a letter; and end with a letter or digit."
  }
}
