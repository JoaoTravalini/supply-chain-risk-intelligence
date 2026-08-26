"""Synchronous HTTP boundary utilities for external source adapters."""

from __future__ import annotations

import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from types import TracebackType
from typing import cast

import httpx
from pydantic import JsonValue, TypeAdapter, ValidationError

from supplychain.integrations.errors import (
    ExternalSourceError,
    ExternalSourceHttpError,
    ExternalSourcePayloadError,
    ExternalSourceTimeoutError,
    ExternalSourceTransportError,
)

DEFAULT_USER_AGENT = "SupplyChain-Sentinel/0.1"
RETRYABLE_STATUS_CODES = frozenset({408, 429, 500, 502, 503, 504})
NON_RETRYABLE_STATUS_CODES = frozenset({400, 401, 403, 404, 422})

JsonObject = dict[str, JsonValue]
QueryParams = Mapping[str, str | int | float | bool | None]
Sleep = Callable[[float], None]

_JSON_OBJECT_ADAPTER: TypeAdapter[JsonObject] = TypeAdapter(JsonObject)


@dataclass(frozen=True)
class TimeoutConfig:
    """Finite timeout configuration for external HTTP requests."""

    connect: float = 5.0
    read: float = 20.0
    write: float = 10.0
    pool: float = 5.0

    def __post_init__(self) -> None:
        for name, value in (
            ("connect", self.connect),
            ("read", self.read),
            ("write", self.write),
            ("pool", self.pool),
        ):
            if value <= 0:
                raise ValueError(f"{name} timeout must be greater than zero")

    def to_httpx_timeout(self) -> httpx.Timeout:
        """Render the boundary timeout contract as an HTTPX timeout."""

        return httpx.Timeout(
            connect=self.connect,
            read=self.read,
            write=self.write,
            pool=self.pool,
        )


@dataclass(frozen=True)
class RetryPolicy:
    """Bounded retry policy for transient external source failures."""

    max_attempts: int = 3
    initial_backoff_seconds: float = 0.25
    max_backoff_seconds: float = 2.0

    def __post_init__(self) -> None:
        if self.max_attempts < 1:
            raise ValueError("max_attempts must be at least one")
        if self.initial_backoff_seconds <= 0:
            raise ValueError("initial_backoff_seconds must be greater than zero")
        if self.max_backoff_seconds <= 0:
            raise ValueError("max_backoff_seconds must be greater than zero")

    def backoff_for_retry(self, retry_number: int) -> float:
        """Return the capped exponential backoff for a one-based retry number."""

        if retry_number < 1:
            raise ValueError("retry_number must be at least one")
        delay = float(self.initial_backoff_seconds * (2 ** (retry_number - 1)))
        return min(delay, self.max_backoff_seconds)


class ExternalHttpClient:
    """Small synchronous GET-only JSON client for external source adapters."""

    def __init__(
        self,
        *,
        timeout: TimeoutConfig | None = None,
        retry_policy: RetryPolicy | None = None,
        user_agent: str = DEFAULT_USER_AGENT,
        sleep: Sleep = time.sleep,
        transport: httpx.BaseTransport | None = None,
        require_https: bool = True,
    ) -> None:
        self.timeout_config = timeout or TimeoutConfig()
        self.retry_policy = retry_policy or RetryPolicy()
        self._sleep = sleep
        self._require_https = require_https
        self._client = httpx.Client(
            timeout=self.timeout_config.to_httpx_timeout(),
            headers={"User-Agent": user_agent},
            transport=transport,
        )

    def __enter__(self) -> ExternalHttpClient:
        return self

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        self.close()

    def close(self) -> None:
        """Close the underlying HTTPX client."""

        self._client.close()

    def get_json_object(self, url: str, *, params: QueryParams | None = None) -> JsonObject:
        """GET an HTTPS URL and return a validated top-level JSON object."""

        parsed_url = httpx.URL(url)
        safe_url = _safe_url(parsed_url)
        if self._require_https and parsed_url.scheme != "https":
            raise ExternalSourceError(
                "External source requests require HTTPS",
                method="GET",
                safe_url=safe_url,
                attempts=0,
            )

        query_params = httpx.QueryParams(params) if params is not None else None

        for attempt in range(1, self.retry_policy.max_attempts + 1):
            try:
                response = self._client.get(parsed_url, params=query_params)
            except httpx.TimeoutException as exc:
                if self._should_retry(attempt):
                    self._sleep(self.retry_policy.backoff_for_retry(attempt))
                    continue
                raise ExternalSourceTimeoutError(
                    "External source request timed out",
                    method="GET",
                    safe_url=safe_url,
                    attempts=attempt,
                ) from exc
            except httpx.TransportError as exc:
                if self._should_retry(attempt):
                    self._sleep(self.retry_policy.backoff_for_retry(attempt))
                    continue
                raise ExternalSourceTransportError(
                    "External source request failed at the transport layer",
                    method="GET",
                    safe_url=safe_url,
                    attempts=attempt,
                ) from exc

            if 200 <= response.status_code < 300:
                return _parse_json_object(response, safe_url=safe_url, attempts=attempt)

            if response.status_code in RETRYABLE_STATUS_CODES and self._should_retry(attempt):
                self._sleep(_retry_delay(response, self.retry_policy, attempt))
                continue

            raise ExternalSourceHttpError(
                "External source returned a non-success HTTP status",
                status_code=response.status_code,
                method="GET",
                safe_url=safe_url,
                attempts=attempt,
            )

        raise AssertionError("retry loop exited unexpectedly")

    def _should_retry(self, attempt: int) -> bool:
        return attempt < self.retry_policy.max_attempts


def _parse_json_object(response: httpx.Response, *, safe_url: str, attempts: int) -> JsonObject:
    try:
        raw_payload = cast(object, response.json())
    except ValueError as exc:
        raise ExternalSourcePayloadError(
            "External source returned invalid JSON",
            method="GET",
            safe_url=safe_url,
            attempts=attempts,
        ) from exc

    try:
        return _JSON_OBJECT_ADAPTER.validate_python(raw_payload)
    except ValidationError as exc:
        raise ExternalSourcePayloadError(
            "External source JSON payload must be a top-level object",
            method="GET",
            safe_url=safe_url,
            attempts=attempts,
        ) from exc


def _retry_delay(response: httpx.Response, retry_policy: RetryPolicy, attempt: int) -> float:
    retry_after = response.headers.get("Retry-After")
    if retry_after is not None:
        try:
            retry_after_seconds = float(retry_after)
        except ValueError:
            return retry_policy.backoff_for_retry(attempt)
        if retry_after_seconds >= 0:
            return min(retry_after_seconds, retry_policy.max_backoff_seconds)
    return retry_policy.backoff_for_retry(attempt)


def _safe_url(url: httpx.URL) -> str:
    host = url.host or ""
    port = f":{url.port}" if url.port is not None else ""
    path = url.path or "/"
    return f"{url.scheme}://{host}{port}{path}"
