from __future__ import annotations

from collections.abc import Callable
from typing import cast

import httpx
import pytest

from supplychain.integrations import (
    DEFAULT_USER_AGENT,
    NON_RETRYABLE_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    ExternalHttpClient,
    ExternalSourceError,
    ExternalSourceHttpError,
    ExternalSourcePayloadError,
    ExternalSourceTimeoutError,
    ExternalSourceTransportError,
    JsonObject,
    RetryPolicy,
    TimeoutConfig,
)

TEST_URL = "https://api.example.test/v1/resource"


def response_handler(
    handler: Callable[[httpx.Request], httpx.Response],
) -> tuple[httpx.MockTransport, list[httpx.Request]]:
    requests: list[httpx.Request] = []

    def wrapped(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return handler(request)

    return httpx.MockTransport(wrapped), requests


def json_response(
    request: httpx.Request,
    status_code: int = 200,
    payload: JsonObject | None = None,
    headers: dict[str, str] | None = None,
) -> httpx.Response:
    return httpx.Response(
        status_code,
        json={} if payload is None else payload,
        headers=headers,
        request=request,
    )


def test_get_json_object_returns_top_level_json_object() -> None:
    transport, _ = response_handler(lambda request: json_response(request, payload={"ok": True}))
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    payload = client.get_json_object(TEST_URL)

    assert payload == {"ok": True}


def test_get_json_object_public_api_imports() -> None:
    assert ExternalHttpClient.__name__ == "ExternalHttpClient"
    assert RetryPolicy(max_attempts=1).max_attempts == 1
    assert TimeoutConfig(connect=1, read=1, write=1, pool=1).read == 1


def test_get_uses_explicit_query_params_without_manual_concatenation() -> None:
    transport, requests = response_handler(lambda request: json_response(request))
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    client.get_json_object(TEST_URL, params={"country": "US", "limit": 10, "active": True})

    assert str(requests[0].url) == (
        "https://api.example.test/v1/resource?country=US&limit=10&active=true"
    )


def test_user_agent_is_centralized_and_contains_no_personal_data() -> None:
    transport, requests = response_handler(lambda request: json_response(request))
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    client.get_json_object(TEST_URL)

    assert requests[0].headers["User-Agent"] == DEFAULT_USER_AGENT
    assert "@" not in DEFAULT_USER_AGENT


def test_custom_timeout_config_is_owned_by_client() -> None:
    timeout = TimeoutConfig(connect=1.0, read=2.0, write=3.0, pool=4.0)
    transport, _ = response_handler(lambda request: json_response(request))
    client = ExternalHttpClient(transport=transport, timeout=timeout, sleep=lambda _: None)

    assert client.timeout_config == timeout


@pytest.mark.parametrize(
    "field",
    ["connect", "read", "write", "pool"],
)
def test_timeout_values_must_be_positive(field: str) -> None:
    values = {"connect": 1.0, "read": 1.0, "write": 1.0, "pool": 1.0}
    values[field] = 0.0

    with pytest.raises(ValueError):
        TimeoutConfig(**values)


def test_retry_policy_requires_at_least_one_attempt() -> None:
    with pytest.raises(ValueError):
        RetryPolicy(max_attempts=0)


@pytest.mark.parametrize(
    "field",
    ["initial_backoff_seconds", "max_backoff_seconds"],
)
def test_retry_policy_backoffs_must_be_positive(field: str) -> None:
    with pytest.raises(ValueError):
        if field == "initial_backoff_seconds":
            RetryPolicy(max_attempts=1, initial_backoff_seconds=0.0, max_backoff_seconds=2.0)
        else:
            RetryPolicy(max_attempts=1, initial_backoff_seconds=0.25, max_backoff_seconds=0.0)


def test_non_https_url_rejected_before_transport_call() -> None:
    calls = 0

    def handler(request: httpx.Request) -> httpx.Response:
        nonlocal calls
        calls += 1
        return json_response(request)

    transport = httpx.MockTransport(handler)
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    with pytest.raises(ExternalSourceError) as exc_info:
        client.get_json_object("http://api.example.test/v1/resource?trace=synthetic")

    assert calls == 0
    assert exc_info.value.safe_url == "http://api.example.test/v1/resource"


def test_successful_response_does_not_retry() -> None:
    transport, requests = response_handler(lambda request: json_response(request))
    sleeps: list[float] = []
    client = ExternalHttpClient(transport=transport, sleep=sleeps.append)

    client.get_json_object(TEST_URL)

    assert len(requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("status_code", sorted(NON_RETRYABLE_STATUS_CODES))
def test_non_retryable_http_statuses_are_not_retried(status_code: int) -> None:
    transport, requests = response_handler(
        lambda request: json_response(request, status_code=status_code)
    )
    sleeps: list[float] = []
    client = ExternalHttpClient(transport=transport, sleep=sleeps.append)

    with pytest.raises(ExternalSourceHttpError) as exc_info:
        client.get_json_object(TEST_URL)

    assert exc_info.value.status_code == status_code
    assert len(requests) == 1
    assert sleeps == []


@pytest.mark.parametrize("status_code", sorted(RETRYABLE_STATUS_CODES))
def test_retryable_http_statuses_are_retried_until_exhausted(status_code: int) -> None:
    transport, requests = response_handler(
        lambda request: json_response(request, status_code=status_code)
    )
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError) as exc_info:
        client.get_json_object(TEST_URL)

    assert exc_info.value.status_code == status_code
    assert exc_info.value.attempts == 2
    assert len(requests) == 2
    assert sleeps == [0.5]


def test_retryable_http_status_eventually_succeeds() -> None:
    statuses = [503, 200]

    def handler(request: httpx.Request) -> httpx.Response:
        return json_response(request, status_code=statuses.pop(0), payload={"ready": True})

    transport, requests = response_handler(handler)
    sleeps: list[float] = []
    client = ExternalHttpClient(transport=transport, sleep=sleeps.append)

    payload = client.get_json_object(TEST_URL)

    assert payload == {"ready": True}
    assert len(requests) == 2
    assert sleeps == [0.25]


def test_http_error_preserves_safe_context_without_response_body_or_query() -> None:
    transport, _ = response_handler(
        lambda request: httpx.Response(
            500,
            text="sensitive response body",
            request=request,
        )
    )
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=1),
        sleep=lambda _: None,
    )

    with pytest.raises(ExternalSourceHttpError) as exc_info:
        client.get_json_object("https://api.example.test/v1/resource?trace=synthetic")

    error = exc_info.value
    assert error.status_code == 500
    assert error.method == "GET"
    assert error.safe_url == "https://api.example.test/v1/resource"
    assert "sensitive response body" not in str(error)
    assert "trace" not in str(error)


def test_exponential_backoff_is_deterministic() -> None:
    transport, _ = response_handler(lambda request: json_response(request, status_code=503))
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(
            max_attempts=4,
            initial_backoff_seconds=0.5,
            max_backoff_seconds=10,
        ),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError):
        client.get_json_object(TEST_URL)

    assert sleeps == [0.5, 1.0, 2.0]


def test_exponential_backoff_is_capped() -> None:
    transport, _ = response_handler(lambda request: json_response(request, status_code=503))
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=4, initial_backoff_seconds=2, max_backoff_seconds=3),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError):
        client.get_json_object(TEST_URL)

    assert sleeps == [2.0, 3.0, 3.0]


def test_retry_after_numeric_header_overrides_backoff() -> None:
    transport, _ = response_handler(
        lambda request: json_response(request, status_code=429, headers={"Retry-After": "1.5"})
    )
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError):
        client.get_json_object(TEST_URL)

    assert sleeps == [1.5]


def test_retry_after_header_is_capped_by_max_backoff() -> None:
    transport, _ = response_handler(
        lambda request: json_response(request, status_code=429, headers={"Retry-After": "999"})
    )
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, max_backoff_seconds=3),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError):
        client.get_json_object(TEST_URL)

    assert sleeps == [3.0]


def test_malformed_retry_after_header_falls_back_to_exponential_backoff() -> None:
    transport, _ = response_handler(
        lambda request: json_response(request, status_code=429, headers={"Retry-After": "soon"})
    )
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError):
        client.get_json_object(TEST_URL)

    assert sleeps == [0.5]


def test_timeout_errors_retry_then_map_to_project_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ReadTimeout("read timed out", request=request)

    transport, requests = response_handler(handler)
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceTimeoutError) as exc_info:
        client.get_json_object(TEST_URL)

    assert len(requests) == 2
    assert sleeps == [0.5]
    assert exc_info.value.method == "GET"
    assert exc_info.value.safe_url == TEST_URL
    assert isinstance(exc_info.value.__cause__, httpx.ReadTimeout)


def test_transport_errors_retry_then_map_to_project_exception() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("connection failed", request=request)

    transport, requests = response_handler(handler)
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceTransportError) as exc_info:
        client.get_json_object(TEST_URL)

    assert len(requests) == 2
    assert sleeps == [0.5]
    assert exc_info.value.method == "GET"
    assert exc_info.value.safe_url == TEST_URL
    assert isinstance(exc_info.value.__cause__, httpx.ConnectError)


def test_invalid_json_maps_to_payload_exception() -> None:
    transport, _ = response_handler(
        lambda request: httpx.Response(200, content=b"not-json", request=request)
    )
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    with pytest.raises(ExternalSourcePayloadError):
        client.get_json_object(TEST_URL)


@pytest.mark.parametrize("body", [b"[]", b'"value"', b"true", b"42"])
def test_non_object_json_payloads_are_rejected(body: bytes) -> None:
    transport, _ = response_handler(
        lambda request: httpx.Response(200, content=body, request=request)
    )
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    with pytest.raises(ExternalSourcePayloadError):
        client.get_json_object(TEST_URL)


def test_payload_error_preserves_safe_context_without_query_string() -> None:
    transport, _ = response_handler(
        lambda request: httpx.Response(200, content=b"not-json", request=request)
    )
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    with pytest.raises(ExternalSourcePayloadError) as exc_info:
        client.get_json_object("https://api.example.test/v1/resource?trace=synthetic")

    assert exc_info.value.method == "GET"
    assert exc_info.value.safe_url == "https://api.example.test/v1/resource"
    assert "trace" not in str(exc_info.value)


def test_client_supports_context_manager_close() -> None:
    transport, _ = response_handler(lambda request: json_response(request, payload={"ok": True}))

    with ExternalHttpClient(transport=transport, sleep=lambda _: None) as client:
        assert client.get_json_object(TEST_URL) == {"ok": True}


def test_retry_backoff_rejects_invalid_retry_number() -> None:
    with pytest.raises(ValueError):
        RetryPolicy().backoff_for_retry(0)


def test_retry_after_negative_value_falls_back_to_exponential_backoff() -> None:
    transport, _ = response_handler(
        lambda request: json_response(request, status_code=429, headers={"Retry-After": "-1"})
    )
    sleeps: list[float] = []
    client = ExternalHttpClient(
        transport=transport,
        retry_policy=RetryPolicy(max_attempts=2, initial_backoff_seconds=0.5),
        sleep=sleeps.append,
    )

    with pytest.raises(ExternalSourceHttpError):
        client.get_json_object(TEST_URL)

    assert sleeps == [0.5]


def test_json_object_allows_nested_json_values() -> None:
    payload = {
        "items": [{"name": "synthetic-source", "values": [1, 2, None]}],
        "active": True,
        "score": 1.5,
    }
    transport, _ = response_handler(
        lambda request: json_response(request, payload=cast(JsonObject, payload))
    )
    client = ExternalHttpClient(transport=transport, sleep=lambda _: None)

    assert client.get_json_object(TEST_URL) == payload
