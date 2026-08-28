# Retry And Dead-Letter Policy

Stage 10C.2B introduces bounded processing disposition for one already-valid
`ReceivedCanonicalEvent`.

Retries remain transport-driven. The application does not maintain a custom
retry database, does not add retry counters to the processing ledger, and does
not run a Python retry loop. The Stage 10B ledger remains responsible only for
logical event idempotency and accepted source revision state.

## Topology

The canonical local Pub/Sub topology is:

```text
topic: canonical-events-v1
subscription: canonical-events-processing-v1
dead-letter topic: canonical-events-dead-letter-v1
dead-letter inspection subscription: canonical-events-dead-letter-inspection-v1
```

The processing subscription is configured with a native Pub/Sub
`DeadLetterPolicy` pointing to `canonical-events-dead-letter-v1`.

The dead-letter inspection subscription is attached to
`canonical-events-dead-letter-v1` so dead-lettered messages have a durable local
queue for future operational inspection or reprocessing. Stage 10C.2B.1 does
not implement a DLQ consumer, pull from that subscription, acknowledge
dead-letter messages, replay messages, or provide an operator UI.

The configured maximum delivery attempts value is `5`, the minimum supported
bounded value in the Pub/Sub API and this project's intended retry boundary.
Managed Pub/Sub dead-letter forwarding is best effort: forwarding can occur
after fewer attempts, additional attempts may occur, and delivery-attempt
tracking is not a strict application transaction counter. A NACK is represented
by setting the acknowledgement deadline to zero.

Exactly-once delivery, message ordering, push delivery, filters, retry topics,
and application retry topics are not configured.

## Native Pub/Sub Semantics

The Pub/Sub client/API exposes subscription-level dead-letter policy. It does
not provide a client operation that directly sends an existing pulled delivery to
the DLQ immediately.

Therefore `ProcessingDisposition.DEAD_LETTER` means application semantic
dead-letter intent. The runtime requests redelivery once for that delivery,
allowing native Pub/Sub dead-letter policy to handle forwarding on a best-effort
delivery-attempt basis. `DEAD_LETTER` does not mean the client directly invokes
a `move_current_message_to_dlq()` operation.

The application does not manually republish the Canonical Event to the DLQ, does
not create a second dead-letter envelope, and does not mutate the Canonical Event
body. The original Pub/Sub message data remains authoritative.

## Delivery Attempts

When `ReceivedCanonicalEvent.delivery_attempt` is present, it must be a positive
integer. Zero, negative, boolean, or non-integer values are rejected at the
policy boundary.

`delivery_attempt` is useful runtime metadata when present, but it is not an
exact globally reliable application retry counter. The processing ledger does
not persist it, and application identity does not use it.

When delivery attempt is unavailable, the policy does not treat the event as
exhausted. For `RETRYABLE` and `UNEXPECTED` failures, unknown attempt maps to
`REDELIVER`. `NON_RETRYABLE` and `REVISION_CONFLICT` still map to
semantic `DEAD_LETTER` intent.

## Disposition Mapping

`RETRYABLE`:

- below attempt budget: `REDELIVER`;
- unknown attempt: `REDELIVER`;
- exhausted attempt: `DEAD_LETTER`.

`UNEXPECTED`:

- below attempt budget: `REDELIVER`;
- unknown attempt: `REDELIVER`;
- exhausted attempt: `DEAD_LETTER`.

`NON_RETRYABLE`:

- semantic `DEAD_LETTER` intent. Native forwarding is not guaranteed to happen
  on the first delivery and can still involve later redelivery before Pub/Sub
  forwards the message.

`REVISION_CONFLICT`:

- semantic `DEAD_LETTER` intent. Native forwarding still follows the
  subscription `DeadLetterPolicy` best-effort delivery-attempt semantics.

`NON_RETRYABLE` and `REVISION_CONFLICT` are not ACKed as success and are not
resolved by rerunning the handler inside the same invocation.

## Runtime Coordinator

`ProcessingRuntimeCoordinator` wraps the existing `ProcessingCoordinator` for
one delivery. It does not change the safe Stage 10C.1 order:

```text
handler
-> record_success
-> ACK
```

Successful `PROCESSED`, `DUPLICATE`, and `STALE_REVISION` results are already
acknowledged by the processing coordinator, so the runtime layer performs no
second transport action.

For handler failures, the runtime classifies the exception and applies the
bounded disposition once. It never calls the handler twice in one invocation and
never loops.

For revision conflicts, the runtime classifies the coordinator result as
`REVISION_CONFLICT`, applies semantic `DEAD_LETTER` intent, and requests
redelivery once for native Pub/Sub policy handling.

Ledger, persistence, and ACK transport failures are not treated as handler
failures. ACK failure after ledger success remains a separate path: the ACK
exception propagates, no dead-letter policy is applied, and a later redelivery
can safely assess as `DUPLICATE`.

## Emulator Limitations

The local emulator can be used to create the canonical topic, processing
subscription, DLQ topic, and DLQ inspection subscription with the intended
dead-letter policy. Emulator support for managed-service DLQ forwarding and
delivery-attempt behavior may differ from the managed Pub/Sub service and
should not be treated as proof of production behavior.

Future production Pub/Sub IaC must grant the managed Pub/Sub service agent the
permissions required for native dead-letter forwarding, including permission to
publish to the dead-letter topic and consume or acknowledge from the source
subscription as required by Google Pub/Sub dead-letter semantics. Stage 10C.2B.1
does not modify IAM, OpenTofu, roles, service accounts, or real GCP resources.

Offline tests validate the bounded policy deterministically. Local live smoke is
limited to emulator safety, topology bootstrap when available, and a single
retryable failure redelivery request when the emulator is reachable.

## Non-Goals

Stage 10C.2B does not implement:

- production Pub/Sub IaC;
- long-running worker runtime;
- custom retry-state persistence;
- manual DLQ republishing;
- DLQ envelope schema;
- automatic ack-deadline extension;
- RAW or CORE warehouse writes;
- distributed exactly-once side-effect guarantees.
