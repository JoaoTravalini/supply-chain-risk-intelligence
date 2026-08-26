# Seismic Event Contract

`SeismicEventPayload` is the provider-independent canonical payload for a single
detected seismic event. It is used inside Canonical Event v1 payloads for
`seismic.event.detected` events.

USGS is currently a producer of this canonical payload. The contract is not
USGS-specific business logic, and it does not calculate supply-chain risk.

## Fields

- `latitude`: earthquake epicenter latitude from -90 through 90.
- `longitude`: earthquake epicenter longitude from -180 through 180.
- `depth_km`: earthquake depth in kilometers, from -100 through 1000.
- `magnitude`: provider magnitude value, from -10 through 10.
- `magnitude_type`: optional non-empty provider magnitude type such as `mw`,
  `mb`, or `ml`.
- `place`: non-empty provider descriptive place text.
- `status`: provider review status, currently `automatic` or `reviewed`.
- `tsunami`: strict boolean canonicalized from a provider numeric flag.
- `significance`: non-negative provider catalog significance indicator.
- `source_updated_at`: timezone-aware UTC provider catalog update timestamp.

## Time Semantics

Canonical Event `event_time` is the earthquake occurrence/origin time.

`source_updated_at` is the latest provider catalog revision timestamp
represented by the payload. These timestamps can differ and must not be
substituted for each other.

## Validation

The payload is a Pydantic v2 model. It is strict, immutable after validation,
and rejects unexpected fields.

Coordinates describe the earthquake epicenter, not a supplier or query-center
coordinate. Depth is represented in kilometers. Boolean values are rejected for
numeric seismic fields.

## No Risk Interpretation

Magnitude, tsunami status, and USGS significance are preserved as seismic facts.
Stage 8C does not classify events, calculate supplier impact, estimate
disruption probability, or produce recommendations.
