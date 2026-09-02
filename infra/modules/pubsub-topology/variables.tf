variable "project_id" {
  description = "Project that owns the Pub/Sub topology."
  type        = string
}

variable "labels" {
  description = "Low-cardinality labels applied to Pub/Sub resources."
  type        = map(string)
  default     = {}
}

variable "runtime_service_account_email" {
  description = "Runtime service account that publishes and consumes canonical event messages."
  type        = string
}

variable "ack_deadline_seconds" {
  description = "Processing subscription ack deadline."
  type        = number
  default     = 60
}

variable "max_delivery_attempts" {
  description = "Bounded Pub/Sub delivery attempts before dead-letter routing."
  type        = number
  default     = 5
}

variable "message_retention_duration" {
  description = "Pub/Sub message retention duration."
  type        = string
  default     = "604800s"
}
