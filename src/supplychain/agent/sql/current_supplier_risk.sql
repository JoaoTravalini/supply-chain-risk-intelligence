SELECT
  model_version,
  supplier_id,
  assessed_at,
  risk_score,
  risk_level,
  structural_score,
  weather_score,
  seismic_score,
  criticality_component,
  dependency_component,
  single_source_component,
  lead_time_component,
  relevant_weather_event_count,
  relevant_seismic_event_count,
  evidence_deduplication_keys,
  dominant_factor
FROM `{mart_supplier_risk_current_table}`
WHERE supplier_id = @supplier_id
