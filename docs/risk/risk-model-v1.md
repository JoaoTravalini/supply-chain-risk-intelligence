# Supplier Risk Model v1

Supplier Risk Model v1 is a transparent deterministic portfolio heuristic. It
is not an actuarial model, a statistical probability-of-failure model, or a
trained machine-learning model.

The model's purpose is reproducibility, explainability, auditable factor
decomposition, and a clear upgrade path. Given the same Supplier, Canonical
Events, model configuration, and explicit `assessed_at` timestamp, it produces
the same assessment.

The model version is `1.0.0`.

## Inputs

- Supplier v1 master data from CORE.
- Current Canonical Event v1 records from CORE.
- Explicit UTC `assessed_at` timestamp.
- Risk Model v1 configuration.

The model does not call external services, read environment variables, query
databases, use an LLM, or call `datetime.now()`.

## Structural Risk

Structural risk uses only Supplier v1 fields:

- `criticality`
- `dependency_score`
- `single_source`
- `typical_lead_time_days`

`annual_spend_usd` is intentionally not used as a v1 hazard multiplier.

Criticality components:

- `LOW`: `0.25`
- `MEDIUM`: `0.50`
- `HIGH`: `0.75`
- `CRITICAL`: `1.00`

Other components:

- Dependency: `dependency_score`
- Single source: `false = 0.0`, `true = 1.0`
- Lead time: `clamp(typical_lead_time_days / 365, 0, 1)`

Structural score:

```text
100 * (
  0.30 * criticality_component
  + 0.35 * dependency_component
  + 0.20 * single_source_component
  + 0.15 * lead_time_component
)
```

## Weather Risk

Weather risk uses only `weather.observation.recorded` Canonical Events whose
payload validates as `WeatherObservationPayload`.

Default lookback: 24 hours relative to explicit `assessed_at`.

Boundary semantics are inclusive:

```text
assessed_at - weather_lookback <= event_time <= assessed_at
```

Weather relevance is true when either:

- the event entity is `type = "supplier"` and `id = supplier_id`; or
- the payload coordinates are within 50 km of the Supplier coordinates.

Distance uses deterministic Haversine calculation with the Python standard
library.

Weather hazard:

```text
0.25 * clamp(wind_speed_10m_kmh / 100, 0, 1)
+ 0.35 * clamp(wind_gusts_10m_kmh / 140, 0, 1)
+ 0.25 * clamp(precipitation_mm / 50, 0, 1)
+ 0.15 * clamp(snowfall_cm / 30, 0, 1)
```

`rain_mm` and `weather_code` are preserved facts but are not separate risk
inputs in v1.

For multiple relevant observations, the weather score uses the maximum hazard,
not the sum.

## Seismic Risk

Seismic risk uses only `seismic.event.detected` Canonical Events whose payload
validates as `SeismicEventPayload`.

Default lookback: 7 days relative to explicit `assessed_at`.

Boundary semantics are inclusive:

```text
assessed_at - seismic_lookback <= event_time <= assessed_at
```

Default relevance radius: 1000 km from Supplier coordinates to earthquake
epicenter coordinates.

Magnitude normalization:

```text
clamp((magnitude - 3.0) / 4.0, 0, 1)
```

Distance attenuation:

```text
clamp(1 - distance_km / seismic_relevance_radius_km, 0, 1)
```

Event hazard:

```text
magnitude_factor * distance_factor
```

For multiple relevant earthquakes, the seismic score uses the maximum event
hazard, not the sum. Tsunami and significance values are not used in v1 because
the model does not yet include exposure context required to interpret them
responsibly.

## Overall Score

Overall family weights:

- Structural: `0.50`
- Weather: `0.30`
- Seismic: `0.20`

Overall score:

```text
0.50 * structural_score
+ 0.30 * weather_score
+ 0.20 * seismic_score
```

Scores are rounded deterministically to two decimal places.

## Risk Levels

- `LOW`: `0 <= score < 25`
- `MEDIUM`: `25 <= score < 50`
- `HIGH`: `50 <= score < 75`
- `CRITICAL`: `75 <= score <= 100`

## Evidence

Evidence uses Canonical Event `metadata.deduplication_key`, not Pub/Sub
message IDs, acknowledgement IDs, delivery attempts, or retry metadata.

Evidence keys are deduplicated and sorted deterministically.

## Dominant Factor

`dominant_factor` is selected from weighted contribution to the overall score,
not from the largest raw family score. Exact ties use this deterministic order:

1. `STRUCTURAL`
2. `WEATHER`
3. `SEISMIC`

## Versioning

PATCH versions may clarify or correct non-breaking implementation details.
MINOR versions may add backward-compatible outputs or factors. MAJOR versions
are required for breaking formula, threshold, interpretation, or contract
changes.

Future LLM stages may explain risk outputs, but they must not calculate the
authoritative risk score.
