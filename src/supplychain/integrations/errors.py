"""External source integration exception taxonomy."""

from __future__ import annotations


class ExternalSourceError(Exception):
    """Base exception for external source boundary failures."""

    def __init__(
        self,
        message: str,
        *,
        method: str | None = None,
        safe_url: str | None = None,
        attempts: int | None = None,
    ) -> None:
        super().__init__(message)
        self.method = method
        self.safe_url = safe_url
        self.attempts = attempts


class ExternalSourceTimeoutError(ExternalSourceError):
    """External source request failed because a configured timeout was exceeded."""


class ExternalSourceTransportError(ExternalSourceError):
    """External source request failed because of a transport-level error."""


class ExternalSourceHttpError(ExternalSourceError):
    """External source returned a non-success HTTP status."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        method: str | None = None,
        safe_url: str | None = None,
        attempts: int | None = None,
    ) -> None:
        super().__init__(message, method=method, safe_url=safe_url, attempts=attempts)
        self.status_code = status_code


class ExternalSourcePayloadError(ExternalSourceError):
    """External source returned a response payload that failed boundary validation."""
