# Pub/Sub Messaging

SupplyChain Sentinel uses Google Cloud Pub/Sub as the event-driven messaging backbone for validated Canonical Events. Stage 9A implements the local-emulator foundation and one publisher path for `CanonicalEvent -> Pub/Sub`; it does not implement subscriptions, consumers, warehouse ingestion, retries, dead-letter handling, or end-to-end processing.

## Topic Topology

Stage 9 defines one canonical topic:

```text
canonical-events-v1
```

The topic version aligns with the major generation of the Canonical Event contract. Weather, seismic, and supplier operational events share this topic because the Canonical Event envelope already carries `event_type`, source provenance, schema version, and processing metadata.

Stage 9B owns the first subscription. No subscription is defined in Stage 9A.

## Message Body

The Pub/Sub message data is exactly the serialized Canonical Event envelope. It is not wrapped in a second object such as `{"event": ...}`.

Serialization uses:

- `CanonicalEvent.model_dump(mode="json")`
- standard-library JSON
- deterministic sorted keys
- compact deterministic separators
- UTF-8 bytes

The message body is authoritative. Pub/Sub attributes are only metadata, indexing, and routing hints derived from the validated body. Consumers must validate the message data and must not treat an attribute as more authoritative than the body.

## Message Attributes

The publisher derives this fixed attribute set from the validated event:

- `event_id`
- `event_type`
- `schema_version`
- `source_provider`
- `deduplication_key`
- `correlation_id`
- `producer`
- `producer_version`
- `content_type`

All attribute values are strings.

Attributes must not contain the full payload, raw provider responses, coordinates, source endpoint query strings, credentials, secrets, arbitrary entity data, or ingestion debug dumps. The normal publisher API does not accept caller-supplied arbitrary attributes, preventing metadata that contradicts the event body.

## Identity Semantics

Pub/Sub `message_id` is the transport-assigned identity for one published message.

Canonical `event_id` is the canonical event instance identity generated before transport.

`deduplication_key` is the stable logical event identity for future application idempotency.

These identifiers are distinct. The publisher does not derive `event_id` from Pub/Sub `message_id`, does not use `message_id` as the application deduplication key, and does not use `event_id` as a transport message ID.

## Delivery And Ordering

The architecture assumes at-least-once delivery. Stage 9A does not provide exactly-once application processing, duplicate suppression, retries, revision handling, or dead-letter behavior. Stage 10 owns explicit application idempotency, retry, revision, and DLQ semantics.

Stage 9A does not use Pub/Sub ordering keys. Ordering may be introduced later only for a clearly defined entity or source sequencing requirement.

## Publisher Behavior

`PubSubCanonicalEventPublisher` publishes one validated Canonical Event to the configured topic, waits for Pub/Sub acknowledgement with a finite timeout, and returns a safe receipt containing:

- Pub/Sub `message_id`
- Canonical `event_id`
- topic ID
- topic path

The publisher creates no topics. It maps expected Pub/Sub publish failures into project-owned messaging exceptions without storing message bodies in error text.

## Local Emulator Bootstrap

Local development may bootstrap emulator resources programmatically. The Stage 9A bootstrap operation is explicitly local-emulator-only and ensures `canonical-events-v1` exists in the emulator idempotently.

The bootstrap guard requires `PUBSUB_EMULATOR_HOST` and `PUBSUB_PROJECT_ID`. The emulator host must be a loopback target such as `127.0.0.1:<port>`, `localhost:<port>`, or `[::1]:<port>`.

Future real cloud Pub/Sub resources must be provisioned through OpenTofu/IaC, not implicitly created by application startup. Stage 9A adds no real Pub/Sub infrastructure.
