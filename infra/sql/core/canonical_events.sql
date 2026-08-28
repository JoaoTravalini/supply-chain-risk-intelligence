WITH raw AS (
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
    source_content_fingerprint,
    source_revision_at,
    payload
  FROM `${project_id}.${raw_dataset_id}.${raw_table_id}`
),
key_integrity AS (
  SELECT
    deduplication_key,
    COUNTIF(source_revision_at IS NULL) AS null_revision_rows,
    COUNTIF(source_revision_at IS NOT NULL) AS revisioned_rows,
    COUNT(DISTINCT source_content_fingerprint) AS fingerprint_count,
    MAX(source_revision_at) AS max_source_revision_at
  FROM raw
  GROUP BY deduplication_key
),
unversioned_candidates AS (
  SELECT raw.*
  FROM raw
  INNER JOIN key_integrity USING (deduplication_key)
  WHERE
    key_integrity.revisioned_rows = 0
    AND key_integrity.fingerprint_count = 1
),
unversioned_winners AS (
  SELECT * EXCEPT (representative_rank)
  FROM (
    SELECT
      unversioned_candidates.*,
      ROW_NUMBER() OVER (
        PARTITION BY deduplication_key
        ORDER BY ingested_at ASC, event_id ASC
      ) AS representative_rank
    FROM unversioned_candidates
  )
  WHERE representative_rank = 1
),
top_revision_candidates AS (
  SELECT raw.*
  FROM raw
  INNER JOIN key_integrity USING (deduplication_key)
  WHERE
    key_integrity.null_revision_rows = 0
    AND raw.source_revision_at = key_integrity.max_source_revision_at
),
top_revision_integrity AS (
  SELECT
    deduplication_key,
    source_revision_at,
    COUNT(DISTINCT source_content_fingerprint) AS top_revision_fingerprint_count
  FROM top_revision_candidates
  GROUP BY deduplication_key, source_revision_at
),
revisioned_winners AS (
  SELECT * EXCEPT (representative_rank, top_revision_fingerprint_count)
  FROM (
    SELECT
      top_revision_candidates.*,
      top_revision_integrity.top_revision_fingerprint_count,
      ROW_NUMBER() OVER (
        PARTITION BY top_revision_candidates.deduplication_key
        ORDER BY top_revision_candidates.ingested_at ASC, top_revision_candidates.event_id ASC
      ) AS representative_rank
    FROM top_revision_candidates
    INNER JOIN top_revision_integrity
      USING (deduplication_key, source_revision_at)
    WHERE top_revision_integrity.top_revision_fingerprint_count = 1
  )
  WHERE representative_rank = 1
)
SELECT * FROM unversioned_winners
UNION ALL
SELECT * FROM revisioned_winners
