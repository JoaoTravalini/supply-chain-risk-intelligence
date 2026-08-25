output "bigquery_dataset_ids" {
  description = "BigQuery analytical dataset IDs declared by this root module."
  value = {
    raw  = google_bigquery_dataset.raw.dataset_id
    core = google_bigquery_dataset.core.dataset_id
    mart = google_bigquery_dataset.mart.dataset_id
  }
}
