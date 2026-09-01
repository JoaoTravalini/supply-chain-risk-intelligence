SELECT
  s.supplier_id,
  s.name,
  s.category,
  s.criticality,
  s.country_code,
  s.region,
  s.city,
  s.annual_spend_usd,
  s.typical_lead_time_days,
  s.dependency_score,
  s.single_source,
  r.assessed_at,
  r.risk_score,
  r.risk_level,
  r.model_version,
  r.structural_score,
  r.weather_score,
  r.seismic_score,
  r.dominant_factor,
  r.criticality_component,
  r.dependency_component,
  r.single_source_component,
  r.lead_time_component,
  r.relevant_weather_event_count,
  r.relevant_seismic_event_count,
  r.evidence_deduplication_keys
FROM `{core_suppliers_table}` AS s
JOIN `{mart_supplier_risk_current_table}` AS r
  ON s.supplier_id = r.supplier_id
ORDER BY r.risk_score DESC, s.supplier_id ASC
LIMIT @limit
