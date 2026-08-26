# USGS Seismic Adapter

Stage 8C introduces the USGS seismic adapter. It performs one bounded nearby
earthquake query, validates the USGS GeoJSON response surface consumed by the
platform, and maps each returned earthquake feature into Canonical Event v1.

USGS does not endorse this project, and this repository does not claim a USGS
service-level agreement.

## Provider Endpoint

The adapter uses the official USGS FDSN Event Web Service query endpoint:

```text
https://earthquake.usgs.gov/fdsnws/event/1/query
```

Requests use `GET` through the project `ExternalHttpClient` boundary and always
set:

- `format=geojson`
- `eventtype=earthquake`
- `orderby=time-asc`

No API key or credential configuration is implemented.

## Nearby Query Policy

The adapter supports a circle search around one query center:

- latitude from -90 through 90
- longitude from -180 through 180
- `maxradiuskm` greater than 0 and no more than 1000 km
- timezone-aware `starttime` and `endtime`, normalized to explicit UTC
- `starttime < endtime`
- non-negative `minmagnitude`
- explicit result limit from 1 through 500, default 100

The 1000 km application radius and 500 result maximum are conservative
portfolio bounds to prevent accidental broad catalog pulls from a nearby-event
operation.

## GeoJSON Validation

The adapter validates the consumed response surface:

- top-level `type=FeatureCollection`
- metadata `count`
- feature array
- each feature `type=Feature`
- native feature `id`
- consumed properties
- Point geometry

USGS Point coordinates are interpreted in provider order:

```text
longitude, latitude, depth
```

The adapter does not parse `place` into country, region, or city and does not
geocode earthquake coordinates.

## Source Identity

USGS provides a native stable Feature `id`. The adapter uses that value directly
as `source.source_event_id`.

It does not hash, synthesize, or combine the ID with coordinates, update time,
query center, entity context, correlation lineage, payload measurements, or
Canonical Event instance identity.

## Event Time And Revision Time

USGS property `time` is the earthquake occurrence/origin time. It becomes
Canonical Event `event_time` as a timezone-aware UTC datetime.

USGS property `updated` is the provider catalog revision timestamp. It becomes
`source_updated_at` inside `SeismicEventPayload`.

The same USGS event can be revised while retaining the same Feature ID and
earthquake occurrence time. Future RAW/CORE processing must distinguish exact
duplicate delivery from a newer provider revision of the same logical event.
Stage 8C documents this invariant but does not implement warehouse revision or
upsert behavior.

## Error Handling

Timeout, retry, Retry-After, HTTP status, transport, and top-level JSON parsing
behavior is delegated to `ExternalHttpClient`.

USGS-specific GeoJSON validation failures become `ExternalSourcePayloadError`
with safe endpoint context. Raw provider response bodies and query strings are
not stored in project exceptions.

## Testing Policy

Pytest remains network-free. USGS behavior is tested using `httpx.MockTransport`
through `ExternalHttpClient`.

A single manual smoke query may run after offline quality gates. The smoke
response must not be persisted or committed.

## Limitations

Stage 8C does not implement scheduled collection, supplier correlation
persistence, Pub/Sub publishing, BigQuery loading, revision-aware CORE
processing, transformations, risk scoring, LangGraph, or Streamlit behavior.
