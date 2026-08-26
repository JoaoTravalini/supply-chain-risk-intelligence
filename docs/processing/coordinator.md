# Processing Coordinator

Stage 10C.1 introduces the safe processing coordinator for one already-valid
`ReceivedCanonicalEvent`.

The coordinator is the boundary that orders ledger assessment, business handler
execution, successful ledger mutation, and transport acknowledgement. It does
not pull messages, deserialize Pub/Sub data, validate attributes, run a worker
loop, retry failures, request redelivery, or route messages to a DLQ.

## Scope

The coordinator receives one `ReceivedCanonicalEvent` that Stage 9 has already
validated as a Canonical Event. The only supported processing unit is a single
delivery.

```text
ReceivedCanonicalEvent
-> ProcessingLedger.assess(event)
-> CanonicalEventHandler.handle(event)
-> ProcessingLedger.record_success(event)
-> acknowledge(received event)
```

The handler is represented by the `CanonicalEventHandler` protocol and receives
only the Canonical Event body. Transport metadata such as Pub/Sub `message_id`
and `ack_id` is not business identity and is not passed as idempotency state.

The acknowledgement boundary is represented by the `MessageAcknowledger`
protocol. The existing Pub/Sub consumer satisfies this boundary through its
explicit `acknowledge(...)` method.

## Safe Processing Order

For `NEW` and `NEWER_REVISION`, the required order is:

1. `ledger.assess(event)`
2. `handler.handle(event)`
3. `ledger.record_success(event)`
4. transport ACK

The ledger is mutated only after the handler succeeds. ACK happens only after
the post-handler ledger mutation returns a resolution that is safe to
acknowledge.

## Resolution Behavior

Initial `assess(event)` behavior:

- `NEW`: run the handler, call `record_success`, then decide ACK from the
  actual `record_success` result.
- `NEWER_REVISION`: run the handler, call `record_success`, then decide ACK from
  the actual `record_success` result.
- `DUPLICATE`: skip handler, skip `record_success`, ACK.
- `STALE_REVISION`: skip handler, skip `record_success`, ACK.
- `REVISION_CONFLICT`: skip handler, skip `record_success`, do not ACK.

Post-handler `record_success(event)` behavior:

- `NEW`: ACK.
- `NEWER_REVISION`: ACK.
- `DUPLICATE`: ACK.
- `STALE_REVISION`: ACK.
- `REVISION_CONFLICT`: do not ACK.

The post-handler result is authoritative because concurrent or out-of-order
processing may change the ledger state between `assess` and `record_success`.

## Failure Behavior

Failures propagate to the caller without automatic recovery policy in Stage
10C.1:

- `ledger.assess` failure: no handler, no ACK.
- handler failure: no `record_success`, no ACK.
- `ledger.record_success` failure after handler success: no ACK and no second
  handler attempt.
- ACK failure after ledger success: propagate the ACK failure, do not rollback
  the ledger, and do not call the handler again inside the same coordinator
  invocation.

The coordinator does not call the redelivery primitive and does not NACK
messages. Retry counters, backoff, delivery-attempt policy, poison-message
handling, and DLQ routing remain deferred.

## ACK Failure And Redelivery

If the handler succeeds and `record_success` persists success but the ACK fails,
the ledger remains the record of successful processing. A later redelivery of
the same logical event is expected to assess as `DUPLICATE`, skip the handler,
and ACK successfully if the transport acknowledgement succeeds.

This protects against running the local handler twice after a successful ledger
write. It does not provide a distributed exactly-once transaction around all
future business side effects.

## Result

`ProcessingCoordinatorResult` reports:

- `outcome`;
- ledger `resolution`;
- Canonical Event `event_id`;
- logical `deduplication_key`;
- whether the delivery was acknowledged.

The result intentionally does not expose Pub/Sub `message_id` or `ack_id` as
processing identity.

## Exactly-Once Limitation

Stage 10C.1 provides safe local ordering around handler execution, ledger
mutation, and ACK. It does not guarantee distributed exactly-once business side
effects across future RAW writes, CORE writes, external systems, or Pub/Sub
acknowledgement.

Future durable processing stages must define retry, redelivery, DLQ, and
warehouse-write semantics explicitly before claiming stronger guarantees.
