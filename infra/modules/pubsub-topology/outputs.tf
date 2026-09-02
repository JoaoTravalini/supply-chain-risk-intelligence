output "canonical_events_topic_name" {
  description = "Canonical events topic name."
  value       = google_pubsub_topic.canonical_events.name
}

output "processing_subscription_name" {
  description = "Processing subscription name."
  value       = google_pubsub_subscription.processing.name
}

output "dead_letter_topic_name" {
  description = "Dead-letter topic name."
  value       = google_pubsub_topic.dead_letter.name
}

output "dead_letter_inspection_subscription_name" {
  description = "Dead-letter inspection subscription name."
  value       = google_pubsub_subscription.dead_letter_inspection.name
}
