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
from supplychain.integrations.open_meteo import (
    OPEN_METEO_CURRENT_VARIABLES,
    OPEN_METEO_FORECAST_ENDPOINT,
    OpenMeteoWeatherAdapter,
    generate_open_meteo_source_event_id,
    normalize_open_meteo_coordinate,
)
from supplychain.integrations.usgs import (
    USGS_DEFAULT_LIMIT,
    USGS_MAX_LIMIT,
    USGS_MAX_RADIUS_KM,
    USGS_QUERY_ENDPOINT,
    UsgsSeismicAdapter,
    format_usgs_datetime,
)

__all__ = [
    "DEFAULT_USER_AGENT",
    "NON_RETRYABLE_STATUS_CODES",
    "OPEN_METEO_CURRENT_VARIABLES",
    "OPEN_METEO_FORECAST_ENDPOINT",
    "RETRYABLE_STATUS_CODES",
    "USGS_DEFAULT_LIMIT",
    "USGS_MAX_LIMIT",
    "USGS_MAX_RADIUS_KM",
    "USGS_QUERY_ENDPOINT",
    "ExternalHttpClient",
    "ExternalSourceError",
    "ExternalSourceHttpError",
    "ExternalSourcePayloadError",
    "ExternalSourceTimeoutError",
    "ExternalSourceTransportError",
    "JsonObject",
    "OpenMeteoWeatherAdapter",
    "QueryParams",
    "RetryPolicy",
    "TimeoutConfig",
    "UsgsSeismicAdapter",
    "format_usgs_datetime",
    "generate_open_meteo_source_event_id",
    "normalize_open_meteo_coordinate",
]
