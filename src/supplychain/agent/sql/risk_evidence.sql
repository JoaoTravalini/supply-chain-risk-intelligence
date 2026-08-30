SELECT
  event_id,
  event_type,
  schema_version,
  event_time,
  ingested_at,
  source_provider,
  source_endpoint,
  source_event_id,
  source_request_id,
  entity_type,
  entity_id,
  location_country_code,
  location_region,
  correlation_id,
  producer,
  producer_version,
  deduplication_key,
  payload
FROM `{core_canonical_events_view}`
WHERE deduplication_key IN UNNEST(@evidence_deduplication_keys)
ORDER BY event_time ASC, deduplication_key ASC
