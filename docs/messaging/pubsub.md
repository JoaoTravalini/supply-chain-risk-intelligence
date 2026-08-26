# Pub/Sub Messaging

SupplyChain Sentinel uses Google Cloud Pub/Sub as the event-driven messaging backbone for validated Canonical Events. Stage 9 implements the local-emulator foundation, one publisher path for `CanonicalEvent -> Pub/Sub`, one pull subscription, and a synchronous pull consumer. Stage 10 adds local processing idempotency, revision-aware ledger resolution, and a one-message coordinator that ACKs only after safe ledger/handler ordering. It does not implement warehouse ingestion, retries, dead-letter handling, or long-running worker runtime.

## Topic Topology

Stage 9 defines one canonical topic:

```text
canonical-events-v1
```

Stage 9B defines one canonical processing subscription:

```text
canonical-events-processing-v1
```

The topic version aligns with the major generation of the Canonical Event contract. Weather, seismic, and supplier operational events share this topic because the Canonical Event envelope already carries `event_type`, source provenance, schema version, and processing metadata.

The subscription represents the generic canonical-event processing boundary. It does not imply BigQuery loading, risk calculation, provider-specific processing, or exactly-once business semantics.

## Message Body

The Pub/Sub message data is exactly the serialized Canonical Event envelope. It is not wrapped in a second object such as `{"event": ...}`.

Serialization uses:

- `CanonicalEvent.model_dump(mode="json")`
- standard-library JSON
- deterministic sorted keys
- compact deterministic separators
- UTF-8 bytes

The message body is authoritative. Pub/Sub attributes are only metadata, indexing, and routing hints derived from the validated body. Consumers validate the message data as `CanonicalEvent` and must not treat an attribute as more authoritative than the body.

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

The Stage 9B consumer requires the standard publisher attributes and validates them against the deserialized Canonical Event. Attribute mismatches fail with a project-owned integrity error. Unknown extra attributes are ignored and do not become application data.

## Identity Semantics

Pub/Sub `message_id` is the transport-assigned identity for one published message.

Canonical `event_id` is the canonical event instance identity generated before transport.

`deduplication_key` is the stable logical event identity for future application idempotency.

`ack_id` is the transport acknowledgement handle for one pulled delivery.

These identifiers are distinct. The publisher does not derive `event_id` from Pub/Sub `message_id`, does not use `message_id` as the application deduplication key, and does not use `event_id` as a transport message ID. The consumer does not use `message_id` or `ack_id` as business identity.

## Delivery And Ordering

The architecture assumes at-least-once delivery. The same Canonical Event may be delivered more than once. Stage 9 does not deduplicate and does not maintain in-memory seen-ID state. Stage 10 owns explicit application idempotency, retry, revision, poison-message, and DLQ semantics.

Stage 9 does not use Pub/Sub ordering keys. Ordering may be introduced later only for a clearly defined entity or source sequencing requirement.

## Publisher Behavior

`PubSubCanonicalEventPublisher` publishes one validated Canonical Event to the configured topic, waits for Pub/Sub acknowledgement with a finite timeout, and returns a safe receipt containing:

- Pub/Sub `message_id`
- Canonical `event_id`
- topic ID
- topic path

The publisher creates no topics. It maps expected Pub/Sub publish failures into project-owned messaging exceptions without storing message bodies in error text.

## Pull Consumer Behavior

`PubSubCanonicalEventConsumer` performs bounded synchronous pulls from `canonical-events-processing-v1`.

The consumer:

- uses a finite pull timeout;
- validates `max_messages`;
- returns immutable `ReceivedCanonicalEvent` objects;
- validates message data as authoritative Canonical Events;
- validates standard attributes against the body;
- preserves Pub/Sub receive order;
- does not automatically acknowledge messages.

`ReceivedCanonicalEvent` contains the validated Canonical Event, Pub/Sub `message_id`, Pub/Sub `ack_id`, and optional delivery attempt when available. It does not expose the raw Google message object.

Acknowledgement is explicit through the consumer acknowledgement API after downstream code decides processing is safe. A redelivery primitive is available by setting the acknowledgement deadline to zero, but it is only a transport operation. Stage 9 does not implement processing retry policy, backoff, DLQ routing, or automatic lease extension.

Stage 10C.1 introduces `ProcessingCoordinator` for one already-valid
`ReceivedCanonicalEvent`. For `NEW` and `NEWER_REVISION` ledger outcomes, the
coordinator runs the handler, records successful ledger state, and only then
ACKs. `DUPLICATE` and `STALE_REVISION` deliveries skip handler execution and
ACK. `REVISION_CONFLICT` skips handler execution and does not ACK. The
coordinator does not request redelivery, implement retry counters, run backoff,
or route to a DLQ.

## Local Emulator Bootstrap

Local development may bootstrap emulator resources programmatically. The Stage 9 bootstrap operation is explicitly local-emulator-only and ensures `canonical-events-v1` and `canonical-events-processing-v1` exist in the emulator idempotently.

The bootstrap guard requires `PUBSUB_EMULATOR_HOST` and `PUBSUB_PROJECT_ID`. The emulator host must be a loopback target such as `127.0.0.1:<port>`, `localhost:<port>`, or `[::1]:<port>`.

Future real cloud Pub/Sub resources must be provisioned through OpenTofu/IaC, not implicitly created by application startup. Stage 9 adds no real Pub/Sub infrastructure.
