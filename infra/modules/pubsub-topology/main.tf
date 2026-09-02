resource "google_pubsub_topic" "canonical_events" {
  project = var.project_id
  name    = "supplychain-canonical-events-v1"
  labels  = var.labels
}

resource "google_pubsub_topic" "dead_letter" {
  project = var.project_id
  name    = "supplychain-canonical-events-dlq"
  labels  = var.labels
}

resource "google_pubsub_subscription" "processing" {
  project                    = var.project_id
  name                       = "supplychain-canonical-events-processor"
  topic                      = google_pubsub_topic.canonical_events.id
  ack_deadline_seconds       = var.ack_deadline_seconds
  message_retention_duration = var.message_retention_duration

  dead_letter_policy {
    dead_letter_topic     = google_pubsub_topic.dead_letter.id
    max_delivery_attempts = var.max_delivery_attempts
  }

  labels = var.labels
}

resource "google_pubsub_subscription" "dead_letter_inspection" {
  project                    = var.project_id
  name                       = "supplychain-canonical-events-dlq-inspection"
  topic                      = google_pubsub_topic.dead_letter.id
  ack_deadline_seconds       = var.ack_deadline_seconds
  message_retention_duration = var.message_retention_duration

  labels = var.labels
}

resource "google_pubsub_topic_iam_member" "runtime_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.canonical_events.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.runtime_service_account_email}"
}

resource "google_pubsub_subscription_iam_member" "runtime_subscriber" {
  project      = var.project_id
  subscription = google_pubsub_subscription.processing.name
  role         = "roles/pubsub.subscriber"
  member       = "serviceAccount:${var.runtime_service_account_email}"
}

resource "google_pubsub_topic_iam_member" "runtime_dead_letter_publisher" {
  project = var.project_id
  topic   = google_pubsub_topic.dead_letter.name
  role    = "roles/pubsub.publisher"
  member  = "serviceAccount:${var.runtime_service_account_email}"
}
