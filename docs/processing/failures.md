# Processing Failure Classification

Stage 10C.2A introduces processing failure classification for valid Canonical
Events after the messaging boundary has already deserialized and validated the
event.

Classification answers:

```text
What kind of processing failure or condition occurred?
```

It does not answer:

```text
What transport action should Pub/Sub take for this delivery?
```

Retry budgets, automatic redelivery, NACK behavior, poison-message policy, and
DLQ routing remain deferred to Stage 10C.2B.

## Handler Failure Contract

Concrete future handlers may intentionally declare business-processing failure
semantics by raising `ProcessingHandlerError` subclasses.

`RetryableProcessingError` means the handler failed, but repeating processing
later may reasonably succeed. Conceptual examples include temporary downstream
unavailability, transient timeout, or temporary resource contention. Stage
10C.2A does not automatically retry this failure.

`NonRetryableProcessingError` means repeating the same event without changing
data, code, or state is not expected to succeed. Conceptual examples include
deterministic unsupported business input, known permanent downstream rejection,
or an explicitly unrecoverable business rule condition. Stage 10C.2A does not
automatically ACK or dead-letter this failure.

These handler exceptions are for valid Canonical Event processing. Malformed
Pub/Sub DATA and message-attribute integrity failures happen before the
`ProcessingCoordinator` receives a valid event and are outside this contract.

## Unexpected Failures

Arbitrary exceptions such as `ValueError`, `RuntimeError`, and programming bugs
remain distinct from declared handler errors. They classify as `UNEXPECTED`.

Retryability is not inferred from exception message text, exception names, or
large hardcoded exception lists. Unknown software failures must remain visible to
callers and must not be silently wrapped as retryable or non-retryable handler
failures.

## Revision Conflicts

`ProcessingResolution.REVISION_CONFLICT` is a semantic ledger condition, not a
handler exception. It classifies as `REVISION_CONFLICT` explicitly.

A revision conflict is not automatically retryable. A repeated delivery by
itself cannot prove which conflicting source version is authoritative.

## Classification Result

`ProcessingFailure` is an immutable safe result containing only:

- failure kind;
- Canonical Event `event_id` when available;
- logical `deduplication_key` when available;
- exception type name when an exception exists.

It does not include the full payload, Pub/Sub `ack_id`, message body, traceback,
arbitrary exception args, or exception message text.

## Disposition Boundary

`ProcessingFailureKind.RETRYABLE` does not itself mean NACK.
`ProcessingFailureKind.NON_RETRYABLE` does not itself mean ACK.
`ProcessingFailureKind.REVISION_CONFLICT` does not itself mean DLQ.
`ProcessingFailureKind.UNEXPECTED` does not automatically mean retry.

Stage 10C.2B will map failure classification plus bounded attempt state to
transport and dead-letter disposition. Stage 10C.2A implements no retry loop, no
attempt accounting, no automatic NACK/redelivery, no DLQ publisher, no
ack-deadline extension, and no worker runtime.
