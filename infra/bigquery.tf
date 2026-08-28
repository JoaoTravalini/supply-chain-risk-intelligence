locals {
  common_dataset_labels = {
    application = "supplychain-sentinel"
    environment = "development"
    managed_by  = "opentofu"
  }
}

resource "google_bigquery_dataset" "raw" {
  dataset_id                      = "supplychain_raw"
  friendly_name                   = "SupplyChain RAW"
  description                     = "Append-oriented analytical landing layer for source records, provenance, ingestion metadata, replay, debugging, and audit use cases."
  location                        = var.bigquery_location
  default_table_expiration_ms     = var.bigquery_sandbox_default_expiration_ms
  default_partition_expiration_ms = var.bigquery_sandbox_default_expiration_ms

  labels = merge(local.common_dataset_labels, {
    data_layer = "raw"
  })
}

resource "google_bigquery_dataset" "core" {
  dataset_id                      = "supplychain_core"
  friendly_name                   = "SupplyChain CORE"
  description                     = "Canonical analytical layer for typed, normalized, validated, deduplicated, domain-oriented records."
  location                        = var.bigquery_location
  default_table_expiration_ms     = var.bigquery_sandbox_default_expiration_ms
  default_partition_expiration_ms = var.bigquery_sandbox_default_expiration_ms

  labels = merge(local.common_dataset_labels, {
    data_layer = "core"
  })
}

resource "google_bigquery_dataset" "mart" {
  dataset_id                      = "supplychain_mart"
  friendly_name                   = "SupplyChain MART"
  description                     = "Business-facing analytical layer for supplier risk analytics, historical risk, factor decomposition, dashboards, and agent tools."
  location                        = var.bigquery_location
  default_table_expiration_ms     = var.bigquery_sandbox_default_expiration_ms
  default_partition_expiration_ms = var.bigquery_sandbox_default_expiration_ms

  labels = merge(local.common_dataset_labels, {
    data_layer = "mart"
  })
}

resource "google_bigquery_table" "raw_canonical_events" {
  dataset_id          = google_bigquery_dataset.raw.dataset_id
  table_id            = "canonical_events"
  friendly_name       = "RAW Canonical Events"
  description         = "Append-oriented Canonical Event v1 source-version history table populated through BigQuery batch load jobs."
  deletion_protection = false
  schema              = file("${path.module}/schemas/bigquery/raw/canonical_events.json")

  time_partitioning {
    type  = "DAY"
    field = "ingested_at"
  }

  clustering = [
    "event_type",
    "source_provider",
    "deduplication_key",
  ]

  labels = merge(local.common_dataset_labels, {
    data_layer = "raw"
  })
}

resource "google_bigquery_table" "core_canonical_events" {
  dataset_id          = google_bigquery_dataset.core.dataset_id
  table_id            = "canonical_events"
  friendly_name       = "CORE Canonical Events"
  description         = "Sandbox-compatible current Canonical Event view over RAW history with revision-safe conflict exclusion."
  deletion_protection = false

  view {
    query = templatefile("${path.module}/sql/core/canonical_events.sql", {
      project_id     = var.project_id
      raw_dataset_id = google_bigquery_dataset.raw.dataset_id
      raw_table_id   = google_bigquery_table.raw_canonical_events.table_id
    })
    use_legacy_sql = false
  }

  labels = merge(local.common_dataset_labels, {
    data_layer = "core"
  })
}

resource "google_bigquery_table" "core_suppliers" {
  dataset_id          = google_bigquery_dataset.core.dataset_id
  table_id            = "suppliers"
  friendly_name       = "CORE Suppliers"
  description         = "Supplier v1 master-data snapshot table loaded through BigQuery batch load jobs."
  deletion_protection = false
  schema              = file("${path.module}/schemas/bigquery/core/suppliers.json")

  labels = merge(local.common_dataset_labels, {
    data_layer = "core"
  })
}

resource "google_bigquery_table" "mart_supplier_risk_current" {
  dataset_id          = google_bigquery_dataset.mart.dataset_id
  table_id            = "supplier_risk_current"
  friendly_name       = "MART Supplier Risk Current"
  description         = "Latest deterministic Supplier Risk Model v1 assessment snapshot loaded through BigQuery batch load jobs."
  deletion_protection = false
  schema              = file("${path.module}/schemas/bigquery/mart/supplier_risk_assessments.json")

  labels = merge(local.common_dataset_labels, {
    data_layer = "mart"
  })
}

resource "google_bigquery_table" "mart_supplier_risk_history" {
  dataset_id          = google_bigquery_dataset.mart.dataset_id
  table_id            = "supplier_risk_history"
  friendly_name       = "MART Supplier Risk History"
  description         = "Append-oriented deterministic Supplier Risk Model v1 assessment history loaded through BigQuery batch load jobs."
  deletion_protection = false
  schema              = file("${path.module}/schemas/bigquery/mart/supplier_risk_assessments.json")

  time_partitioning {
    type  = "DAY"
    field = "assessed_at"
  }

  clustering = [
    "risk_level",
    "supplier_id",
  ]

  labels = merge(local.common_dataset_labels, {
    data_layer = "mart"
  })
}
