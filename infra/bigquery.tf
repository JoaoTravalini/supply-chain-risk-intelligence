locals {
  common_dataset_labels = {
    application = "supplychain-sentinel"
    environment = "development"
    managed_by  = "opentofu"
  }
}

resource "google_bigquery_dataset" "raw" {
  dataset_id    = "supplychain_raw"
  friendly_name = "SupplyChain RAW"
  description   = "Append-oriented analytical landing layer for source records, provenance, ingestion metadata, replay, debugging, and audit use cases."
  location      = var.bigquery_location

  labels = merge(local.common_dataset_labels, {
    data_layer = "raw"
  })
}

resource "google_bigquery_dataset" "core" {
  dataset_id    = "supplychain_core"
  friendly_name = "SupplyChain CORE"
  description   = "Canonical analytical layer for typed, normalized, validated, deduplicated, domain-oriented records."
  location      = var.bigquery_location

  labels = merge(local.common_dataset_labels, {
    data_layer = "core"
  })
}

resource "google_bigquery_dataset" "mart" {
  dataset_id    = "supplychain_mart"
  friendly_name = "SupplyChain MART"
  description   = "Business-facing analytical layer for supplier risk analytics, historical risk, factor decomposition, dashboards, and agent tools."
  location      = var.bigquery_location

  labels = merge(local.common_dataset_labels, {
    data_layer = "mart"
  })
}
