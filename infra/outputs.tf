output "bigquery_dataset_ids" {
  description = "BigQuery analytical dataset IDs declared by this root module."
  value = {
    raw  = google_bigquery_dataset.raw.dataset_id
    core = google_bigquery_dataset.core.dataset_id
    mart = google_bigquery_dataset.mart.dataset_id
  }
}

output "bigquery_table_ids" {
  description = "BigQuery table and view IDs declared by this root module."
  value = {
    raw_canonical_events  = google_bigquery_table.raw_canonical_events.table_id
    core_canonical_events = google_bigquery_table.core_canonical_events.table_id
    core_suppliers        = google_bigquery_table.core_suppliers.table_id
    mart_risk_current     = google_bigquery_table.mart_supplier_risk_current.table_id
    mart_risk_history     = google_bigquery_table.mart_supplier_risk_history.table_id
  }
}
