"""Context-local correlation identifiers for logs and traces."""

from __future__ import annotations

from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, replace
from uuid import UUID, uuid4


@dataclass(frozen=True, slots=True)
class ObservabilityContext:
    """Safe identifiers that may correlate one operation across telemetry."""

    request_id: str | None = None
    correlation_id: str | None = None
    event_id: str | None = None
    investigation_id: str | None = None
    thread_id: str | None = None

    def merged(
        self,
        *,
        request_id: str | UUID | None = None,
        correlation_id: str | UUID | None = None,
        event_id: str | UUID | None = None,
        investigation_id: str | UUID | None = None,
        thread_id: str | UUID | None = None,
    ) -> ObservabilityContext:
        """Return a copy with explicitly provided identifiers replaced."""

        return replace(
            self,
            request_id=_string_id(request_id) if request_id is not None else self.request_id,
            correlation_id=(
                _string_id(correlation_id) if correlation_id is not None else self.correlation_id
            ),
            event_id=_string_id(event_id) if event_id is not None else self.event_id,
            investigation_id=(
                _string_id(investigation_id)
                if investigation_id is not None
                else self.investigation_id
            ),
            thread_id=_string_id(thread_id) if thread_id is not None else self.thread_id,
        )

    def log_fields(self) -> dict[str, str]:
        """Return non-empty fields suitable for logs and trace attributes."""

        return {
            key: value
            for key, value in {
                "request_id": self.request_id,
                "correlation_id": self.correlation_id,
                "event_id": self.event_id,
                "investigation_id": self.investigation_id,
                "thread_id": self.thread_id,
            }.items()
            if value is not None
        }


_CURRENT_CONTEXT: ContextVar[ObservabilityContext | None] = ContextVar(
    "supplychain_observability_context",
    default=None,
)


def current_observability_context() -> ObservabilityContext:
    """Return the active context-local observability identifiers."""

    return _CURRENT_CONTEXT.get() or ObservabilityContext()


def new_request_id() -> str:
    """Generate a request identifier for an application operation boundary."""

    return str(uuid4())


@contextmanager
def bind_observability_context(
    *,
    request_id: str | UUID | None = None,
    correlation_id: str | UUID | None = None,
    event_id: str | UUID | None = None,
    investigation_id: str | UUID | None = None,
    thread_id: str | UUID | None = None,
    generate_request_id: bool = False,
) -> Iterator[ObservabilityContext]:
    """Bind identifiers for the current synchronous operation and restore them after."""

    current = current_observability_context()
    resolved_request_id = request_id
    if resolved_request_id is None and generate_request_id and current.request_id is None:
        resolved_request_id = new_request_id()
    updated = current.merged(
        request_id=resolved_request_id,
        correlation_id=correlation_id,
        event_id=event_id,
        investigation_id=investigation_id,
        thread_id=thread_id,
    )
    token = _CURRENT_CONTEXT.set(updated)
    try:
        yield updated
    finally:
        _CURRENT_CONTEXT.reset(token)


def _string_id(value: str | UUID) -> str:
    text = str(value).strip()
    if not text:
        raise ValueError("observability identifier must not be blank")
    return text
