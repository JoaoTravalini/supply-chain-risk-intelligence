# Open-Meteo Weather Adapter

Stage 8B introduces the Open-Meteo current-weather adapter. It retrieves one
current weather observation for one latitude/longitude pair, validates the
provider response, converts it into `WeatherObservationPayload`, and wraps that
payload in Canonical Event v1.

Weather data by Open-Meteo.com, CC BY 4.0.

Open-Meteo is not part of SupplyChain Sentinel and does not endorse this
project. This repository does not claim an Open-Meteo service-level agreement.

## Provider Endpoint

The adapter uses the public Forecast API endpoint:

```text
https://api.open-meteo.com/v1/forecast
```

The current portfolio/demo integration uses the public non-commercial API path
and requires no API key. No API-key configuration is implemented, and endpoint
metadata stored on Canonical Events excludes query strings.

## Requested Variables

The adapter requests only current weather values:

- `temperature_2m`
- `relative_humidity_2m`
- `precipitation`
- `rain`
- `snowfall`
- `weather_code`
- `wind_speed_10m`
- `wind_gusts_10m`

It does not request hourly forecasts, daily forecasts, historical weather, or
unrelated environmental variables.

## Units And Time

Requests set:

- `timezone=UTC`
- `timeformat=unixtime`
- `temperature_unit=celsius`
- `wind_speed_unit=kmh`
- `precipitation_unit=mm`

The adapter validates the returned `current_units` for consumed fields. Unit
mismatches are treated as provider payload errors rather than being silently
interpreted. The provider timestamp is interpreted from Unix seconds as a
timezone-aware UTC `datetime`.

If Open-Meteo returns a non-zero `utc_offset_seconds` despite the UTC request,
the response is rejected.

## Source Identity

Open-Meteo does not return a stable source record identifier for this current
weather response. The adapter derives `source.source_event_id` with SHA-256 over
canonical JSON containing exactly:

- provider: `open-meteo`
- record kind: `current_weather`
- normalized provider response latitude
- normalized provider response longitude
- provider observation timestamp as Unix seconds

Coordinates are normalized to fixed six-decimal strings before hashing. The
source ID uses the prefix `open-meteo-current:`.

The source ID deliberately excludes supplier/entity context, correlation ID,
ingestion time, request ID, weather measurements, Canonical Event `event_id`,
and the final canonical deduplication key.

## Canonical Deduplication

After deriving `source_event_id`, the adapter reuses the existing canonical
deduplication utility. The canonical deduplication identity remains:

- source provider
- event type
- source event ID
- event time normalized to UTC

Entity and location context may be attached to the Canonical Event but do not
change source identity or canonical deduplication identity.

## Error Handling

HTTP transport, timeout, HTTP status, and top-level JSON parsing failures flow
through the Stage 8A `ExternalHttpClient` boundary.

Open-Meteo provider response validation failures become
`ExternalSourcePayloadError` with safe context. The adapter does not persist raw
provider response bodies in exceptions.

## Testing Policy

Pytest remains fully offline. Open-Meteo behavior is tested with
`httpx.MockTransport` through the project `ExternalHttpClient` boundary.

A single manual smoke request may be run after offline quality gates to check
that the public API still matches the encoded provider contract. The smoke
response must not be persisted or committed.

## Limitations

Stage 8B does not implement multi-location batching, scheduled collection,
weather persistence, Pub/Sub publishing, BigQuery loading, transformations, risk
scoring, LangGraph, or Streamlit behavior.
