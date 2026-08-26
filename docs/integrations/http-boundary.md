# External HTTP Boundary

Stage 8A introduces the reusable HTTP boundary used by future external source
adapters. It does not implement any provider-specific adapter, source payload
schema, event generation, Pub/Sub publishing, BigQuery loading, or cloud
resource change.

## Purpose

External source adapters will use this boundary when they need to read JSON from
public HTTPS APIs. The boundary centralizes transport policy so provider
adapters can focus on source-specific mapping and canonical event production in
later stages.

## Public API

The public integration API is exported from `supplychain.integrations`:

- `ExternalHttpClient`
- `TimeoutConfig`
- `RetryPolicy`
- `ExternalSourceError`
- `ExternalSourceTimeoutError`
- `ExternalSourceTransportError`
- `ExternalSourceHttpError`
- `ExternalSourcePayloadError`

The client is synchronous and supports only HTTPS `GET` requests that return a
top-level JSON object.

## Timeout Policy

`TimeoutConfig` owns finite timeout values for:

- connect
- read
- write
- pool

All timeout values must be greater than zero. The defaults are intentionally
finite so external calls cannot wait forever.

## Retry Policy

`RetryPolicy` owns bounded retries with:

- maximum attempts
- initial exponential backoff
- maximum backoff cap

The retry delay is:

```text
initial_backoff_seconds * 2^(retry_number - 1)
```

The result is capped by `max_backoff_seconds`.

The boundary retries transient HTTP response statuses:

- `408`
- `429`
- `500`
- `502`
- `503`
- `504`

The boundary does not retry known permanent client statuses:

- `400`
- `401`
- `403`
- `404`
- `422`

Numeric `Retry-After` values are honored for retryable responses and capped by
`max_backoff_seconds`. Malformed or negative values fall back to exponential
backoff. Tests inject sleep functions so retry behavior remains deterministic
without real waiting.

## JSON Payload Rules

Responses are parsed as JSON only after a successful `2xx` response. Invalid
JSON raises `ExternalSourcePayloadError`.

The accepted response shape is a top-level JSON object. Top-level arrays,
strings, numbers, booleans, and null values are rejected. Provider-specific
payload schemas are deferred to future adapter stages.

## Error Taxonomy

All boundary failures use project exceptions:

- `ExternalSourceTimeoutError` for HTTPX timeout failures
- `ExternalSourceTransportError` for non-timeout HTTPX transport failures
- `ExternalSourceHttpError` for final non-success HTTP statuses
- `ExternalSourcePayloadError` for invalid or malformed JSON payloads

Exceptions preserve safe context such as HTTP method, final attempt count, HTTP
status where applicable, and safe URL origin/path. Query strings and response
bodies are not stored on project exceptions because they can contain sensitive
values.

## Security

External requests require HTTPS by default.

The centralized `User-Agent` is:

```text
SupplyChain-Sentinel/0.1
```

It contains no personal data, account information, or contact address.

Future adapters must pass query parameters through structured parameter
mappings. They must not manually concatenate query strings, log secrets, store
credentials in metadata, or include sensitive query values in exception context.

## Deferred Provider Work

This boundary intentionally does not define Open-Meteo behavior, USGS behavior,
weather payload schemas, seismic payload schemas, source-event identity
derivation, canonical event production, Pub/Sub publishing, or BigQuery writes.
