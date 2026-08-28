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

Retry budgets, redelivery requests, poison-message policy, and DLQ intent are
handled by the later Stage 10C.2B runtime/disposition layer, not by
classification itself.

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

Stage 10C.2B maps failure classification plus bounded delivery-attempt state to
`ACK`, `REDELIVER`, or `DEAD_LETTER` disposition. The mapping remains separate
from classification:

- `RETRYABLE`: redeliver while below the configured attempt budget; dead-letter
  after exhaustion.
- `UNEXPECTED`: redeliver while below the configured attempt budget; dead-letter
  after exhaustion.
- `NON_RETRYABLE`: semantic dead-letter intent, without claiming native Pub/Sub
  forwarding occurs on the first delivery.
- `REVISION_CONFLICT`: semantic dead-letter intent, with actual forwarding still
  controlled by native Pub/Sub best-effort delivery-attempt behavior.

Unknown delivery attempt is not treated as exhausted. For `RETRYABLE` and
`UNEXPECTED`, unknown attempt maps to `REDELIVER`; `NON_RETRYABLE` and
`REVISION_CONFLICT` still map to `DEAD_LETTER`.

Stage 10C.2B still implements no Python retry loop, no custom retry counter, no
DLQ publisher, no ack-deadline extension, no DLQ consumer/replay, and no worker
runtime.
