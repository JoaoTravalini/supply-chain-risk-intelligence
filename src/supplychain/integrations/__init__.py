"""Public integration boundary utilities for SupplyChain Sentinel."""

from supplychain.integrations.errors import (
    ExternalSourceError,
    ExternalSourceHttpError,
    ExternalSourcePayloadError,
    ExternalSourceTimeoutError,
    ExternalSourceTransportError,
)
from supplychain.integrations.http import (
    DEFAULT_USER_AGENT,
    NON_RETRYABLE_STATUS_CODES,
    RETRYABLE_STATUS_CODES,
    ExternalHttpClient,
    JsonObject,
    QueryParams,
    RetryPolicy,
    TimeoutConfig,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "NON_RETRYABLE_STATUS_CODES",
    "RETRYABLE_STATUS_CODES",
    "ExternalHttpClient",
    "ExternalSourceError",
    "ExternalSourceHttpError",
    "ExternalSourcePayloadError",
    "ExternalSourceTimeoutError",
    "ExternalSourceTransportError",
    "JsonObject",
    "QueryParams",
    "RetryPolicy",
    "TimeoutConfig",
]
