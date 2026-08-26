# Weather Observation Contract

`WeatherObservationPayload` is the provider-independent canonical payload for a
single weather observation. It is used inside Canonical Event v1 payloads for
`weather.observation.recorded` events.

Open-Meteo is currently one producer of this payload. The payload itself does
not encode Open-Meteo provider identity; provider identity remains in Canonical
Event source metadata.

## Fields

- `latitude`: observation latitude, from -90 through 90.
- `longitude`: observation longitude, from -180 through 180.
- `temperature_2m_c`: air temperature at 2 meters in Celsius.
- `relative_humidity_2m_pct`: relative humidity at 2 meters, 0 through 100.
- `precipitation_mm`: total precipitation in millimeters, non-negative.
- `rain_mm`: rain in millimeters, non-negative.
- `snowfall_cm`: snowfall in centimeters, non-negative.
- `weather_code`: WMO/Open-Meteo weather code as an integer from 0 through 99.
- `wind_speed_10m_kmh`: wind speed at 10 meters in kilometers per hour,
  non-negative.
- `wind_gusts_10m_kmh`: wind gusts at 10 meters in kilometers per hour,
  non-negative.

## Validation

The payload is a Pydantic v2 model. It is strict, immutable after validation,
and rejects unexpected fields.

Coordinates and weather measurements use defensible boundary validation without
pretending to model all meteorological science. Temperatures may be negative.
Boolean values are rejected for numeric weather fields.

## Weather Code Strategy

`weather_code` is stored as a bounded integer compatible with the WMO weather
codes used by Open-Meteo. Stage 8B does not map weather codes to business risk,
severity labels, disruption categories, or operational recommendations.

## Scope

The contract contains weather facts only. It does not include supplier
identifiers, risk scores, severe-weather classifications, provider response
metadata, request metadata, or persistence metadata.
