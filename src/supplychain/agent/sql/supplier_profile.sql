SELECT
  schema_version,
  supplier_id,
  name,
  category,
  criticality,
  country_code,
  region,
  city,
  latitude,
  longitude,
  annual_spend_usd,
  typical_lead_time_days,
  dependency_score,
  single_source
FROM `{core_suppliers_table}`
WHERE supplier_id = @supplier_id
