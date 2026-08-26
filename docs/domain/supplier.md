# Supplier Domain Contract

The Supplier contract defines canonical supplier master data for SupplyChain Sentinel. It represents relatively stable business attributes used by future synthetic data, analytical modeling, risk calculation, and event correlation.

Stage 7A defines only the domain contract, validation behavior, JSON Schema artifact, and tests. It does not generate supplier records, create dataset files, create BigQuery tables, or implement operational observations.

## Schema Version

The initial Supplier schema version is `1.0.0`. Only `1.0.0` is accepted in Stage 7A, and multi-version dispatch is deferred.

## Supplier ID

`supplier_id` is the internal platform supplier identifier.

Format:

```text
SUP-000001
```

Rules:

- Prefix `SUP-`.
- Exactly six decimal digits.
- Case-sensitive.
- No whitespace-only or malformed values.

Supplier ID generation is deferred to Stage 7B.

## Fields

- `schema_version`: Supplier contract version.
- `supplier_id`: internal supplier identifier.
- `name`: validated supplier display name.
- `category`: controlled business category.
- `criticality`: operational impact if unavailable.
- `location`: stable geographic point for future weather and seismic correlation.
- `annual_spend_usd`: normalized synthetic annual exposure in whole US dollars.
- `typical_lead_time_days`: expected supplier lead time, validated from 1 through 365 days.
- `dependency_score`: dependency value from `0.0` through `1.0`.
- `single_source`: whether the modeled organization relies exclusively on this supplier for the represented supply relationship.

Supplier names in future synthetic data must not intentionally impersonate real companies.

## Category Taxonomy

Stage 7A supports these categories:

- `semiconductors`
- `electronic_components`
- `automotive_components`
- `industrial_equipment`
- `metals`
- `chemicals`
- `packaging`
- `logistics`

This is a controlled business taxonomy. Changes require explicit contract evolution.

## Criticality

Criticality values are:

- `LOW`
- `MEDIUM`
- `HIGH`
- `CRITICAL`

Criticality represents operational or business impact if the supplier becomes unavailable. It is not the supplier's current risk score, and Stage 7A does not derive or calculate it.

## Location

Location is required and contains:

- `country_code`: uppercase two-letter ISO-like code.
- `region`: required non-empty region.
- `city`: required non-empty city.
- `latitude`: numeric value from `-90` through `90`.
- `longitude`: numeric value from `-180` through `180`.

Coordinates are required because future weather and seismic correlation need a stable geographic point. Stage 7A does not perform timezone lookup, geocoding, geohashes, polygons, or network geocoding.

## Exposure, Lead Time, And Dependency

`annual_spend_usd` is a positive strict integer in whole dollars. Stage 7 uses normalized synthetic USD portfolio values for analytical purposes; it is not modeling transactional accounting.

`typical_lead_time_days` is a strict integer from 1 through 365 days. It is not calculated in Stage 7A.

`dependency_score` ranges from `0.0` through `1.0`. Values near `0` indicate easier substitution; values near `1` indicate difficult substitution. This is not a future risk score.

`single_source` is a strict boolean and is not inferred or calculated in Stage 7A.

## Master Data Vs Operational Observations

Supplier master data describes relatively stable supplier attributes:

- identity;
- location;
- category;
- criticality;
- exposure;
- lead-time expectation;
- dependency;
- sourcing concentration.

Dynamic operational performance does not belong in the Supplier master contract. Do not add current risk score, on-time delivery rate, recent delay rate, defect rate, weather risk, seismic risk, anomaly score, or current status metrics to this model. Those belong to operational observations, transformations, or risk analytics in later stages.

## Canonical Event Relationship

The generic Canonical Event envelope remains independent of the Supplier domain model. Future correlated events may use `entity.type = "supplier"` and `entity.id` set to a valid platform supplier ID, but Stage 7A does not add cross-model validation or hardcode supplier behavior into the generic event contract.

## Immutability

Supplier models are immutable after validation. Future updates should conceptually produce a new validated representation rather than mutating an existing model. Persistence and history are deferred.

## Synthetic Data Policy For Stage 7B

The future supplier dataset must be:

- fully synthetic;
- deterministic and reproducible;
- geographically plausible;
- diverse across approved categories and criticality levels;
- generated without external network calls;
- versioned;
- validated through the Supplier contract;
- accompanied by integrity metadata and a checksum.

Stage 7A does not implement the generator or dataset artifact.

## Example

```json
{
  "schema_version": "1.0.0",
  "supplier_id": "SUP-000001",
  "name": "Northstar Components",
  "category": "electronic_components",
  "criticality": "HIGH",
  "location": {
    "country_code": "US",
    "region": "WA",
    "city": "Seattle",
    "latitude": 47.6062,
    "longitude": -122.3321
  },
  "annual_spend_usd": 2500000,
  "typical_lead_time_days": 45,
  "dependency_score": 0.72,
  "single_source": false
}
```
