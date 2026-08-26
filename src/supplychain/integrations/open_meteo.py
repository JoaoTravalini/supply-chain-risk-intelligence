"""Open-Meteo current-weather adapter."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime
from decimal import ROUND_HALF_UP, Decimal
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from supplychain.contracts import (
    CanonicalEvent,
    EntityReference,
    EventMetadata,
    EventType,
    LocationMetadata,
    SourceMetadata,
    WeatherObservationPayload,
    generate_deduplication_key,
)
from supplychain.integrations.errors import ExternalSourcePayloadError
from supplychain.integrations.http import ExternalHttpClient, JsonObject

OPEN_METEO_FORECAST_ENDPOINT = "https://api.open-meteo.com/v1/forecast"
OPEN_METEO_PROVIDER = "open-meteo"
OPEN_METEO_RECORD_KIND = "current_weather"
OPEN_METEO_SOURCE_ID_PREFIX = "open-meteo-current"
OPEN_METEO_COORDINATE_PRECISION = Decimal("0.000001")
OPEN_METEO_PRODUCER = "open-meteo-weather-adapter"
OPEN_METEO_PRODUCER_VERSION = "1.0.0"

OPEN_METEO_CURRENT_VARIABLES = (
    "temperature_2m",
    "relative_humidity_2m",
    "precipitation",
    "rain",
    "snowfall",
    "weather_code",
    "wind_speed_10m",
    "wind_gusts_10m",
)

CoordinateLatitude = Annotated[float, Field(ge=-90.0, le=90.0)]
CoordinateLongitude = Annotated[float, Field(ge=-180.0, le=180.0)]
NonNegativeProviderMeasurement = Annotated[float, Field(ge=0.0)]
ProviderHumidity = Annotated[float, Field(ge=0.0, le=100.0)]
ProviderWeatherCode = Annotated[int, Field(ge=0, le=99)]


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)


class _CoordinateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)

    latitude: CoordinateLatitude
    longitude: CoordinateLongitude

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def reject_boolean_coordinates(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("coordinates must not be booleans")
        return value


class _OpenMeteoCurrentUnits(_ProviderModel):
    time: Literal["unixtime"]
    interval: Literal["seconds"]
    temperature_2m: Literal["\u00b0C"]
    relative_humidity_2m: Literal["%"]
    precipitation: Literal["mm"]
    rain: Literal["mm"]
    snowfall: Literal["cm"]
    weather_code: Literal["wmo code"]
    wind_speed_10m: Literal["km/h"]
    wind_gusts_10m: Literal["km/h"]


class _OpenMeteoCurrent(_ProviderModel):
    time: int
    interval: int
    temperature_2m: float
    relative_humidity_2m: ProviderHumidity
    precipitation: NonNegativeProviderMeasurement
    rain: NonNegativeProviderMeasurement
    snowfall: NonNegativeProviderMeasurement
    weather_code: ProviderWeatherCode
    wind_speed_10m: NonNegativeProviderMeasurement
    wind_gusts_10m: NonNegativeProviderMeasurement

    @field_validator(
        "temperature_2m",
        "relative_humidity_2m",
        "precipitation",
        "rain",
        "snowfall",
        "wind_speed_10m",
        "wind_gusts_10m",
        mode="before",
    )
    @classmethod
    def reject_boolean_measurements(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("provider numeric measurements must not be booleans")
        return value

    @field_validator("time", "interval", "weather_code", mode="before")
    @classmethod
    def reject_boolean_integers(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("provider integer fields must not be booleans")
        return value


class _OpenMeteoCurrentResponse(_ProviderModel):
    latitude: CoordinateLatitude
    longitude: CoordinateLongitude
    utc_offset_seconds: Literal[0]
    current_units: _OpenMeteoCurrentUnits
    current: _OpenMeteoCurrent

    @field_validator("latitude", "longitude", mode="before")
    @classmethod
    def reject_boolean_response_coordinates(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("provider coordinates must not be booleans")
        return value


class OpenMeteoWeatherAdapter:
    """Canonicalize one Open-Meteo current-weather observation per call."""

    def __init__(self, http_client: ExternalHttpClient) -> None:
        self._http_client = http_client

    def fetch_current_weather_event(
        self,
        *,
        latitude: float,
        longitude: float,
        correlation_id: str,
        entity: EntityReference | None = None,
        location: LocationMetadata | None = None,
        ingested_at: datetime | None = None,
    ) -> CanonicalEvent:
        """Fetch current weather and map it into Canonical Event v1."""

        request = _CoordinateRequest.model_validate({"latitude": latitude, "longitude": longitude})
        provider_payload = self._http_client.get_json_object(
            OPEN_METEO_FORECAST_ENDPOINT,
            params={
                "latitude": request.latitude,
                "longitude": request.longitude,
                "current": ",".join(OPEN_METEO_CURRENT_VARIABLES),
                "timezone": "UTC",
                "timeformat": "unixtime",
                "temperature_unit": "celsius",
                "wind_speed_unit": "kmh",
                "precipitation_unit": "mm",
            },
        )
        response = _validate_provider_response(provider_payload)
        return self.canonicalize_current_response(
            response=response,
            correlation_id=correlation_id,
            entity=entity,
            location=location,
            ingested_at=ingested_at,
        )

    def canonicalize_current_response(
        self,
        *,
        response: _OpenMeteoCurrentResponse,
        correlation_id: str,
        entity: EntityReference | None = None,
        location: LocationMetadata | None = None,
        ingested_at: datetime | None = None,
    ) -> CanonicalEvent:
        """Map a validated Open-Meteo current response into Canonical Event v1."""

        event_time = datetime.fromtimestamp(response.current.time, UTC)
        payload = WeatherObservationPayload(
            latitude=response.latitude,
            longitude=response.longitude,
            temperature_2m_c=response.current.temperature_2m,
            relative_humidity_2m_pct=response.current.relative_humidity_2m,
            precipitation_mm=response.current.precipitation,
            rain_mm=response.current.rain,
            snowfall_cm=response.current.snowfall,
            weather_code=response.current.weather_code,
            wind_speed_10m_kmh=response.current.wind_speed_10m,
            wind_gusts_10m_kmh=response.current.wind_gusts_10m,
        )
        source = SourceMetadata(
            provider=OPEN_METEO_PROVIDER,
            endpoint=OPEN_METEO_FORECAST_ENDPOINT,
            source_event_id=generate_open_meteo_source_event_id(
                latitude=response.latitude,
                longitude=response.longitude,
                observed_at=event_time,
            ),
        )
        deduplication_key = generate_deduplication_key(
            source=source,
            event_type=EventType.WEATHER_OBSERVATION_RECORDED,
            event_time=event_time,
        )
        event_data: dict[str, object] = {
            "event_type": EventType.WEATHER_OBSERVATION_RECORDED,
            "event_time": event_time,
            "source": source,
            "entity": entity,
            "location": location,
            "payload": cast(dict[str, JsonValue], payload.model_dump(mode="json")),
            "metadata": EventMetadata(
                correlation_id=correlation_id,
                producer=OPEN_METEO_PRODUCER,
                producer_version=OPEN_METEO_PRODUCER_VERSION,
                deduplication_key=deduplication_key,
            ),
        }
        if ingested_at is not None:
            event_data["ingested_at"] = ingested_at
        return CanonicalEvent.model_validate(event_data)


def generate_open_meteo_source_event_id(
    *,
    latitude: float,
    longitude: float,
    observed_at: datetime,
) -> str:
    """Generate the deterministic Open-Meteo source record identity."""

    observed_at_utc = _require_utc_observation_time(observed_at)
    identity = {
        "latitude": normalize_open_meteo_coordinate(latitude),
        "longitude": normalize_open_meteo_coordinate(longitude),
        "observed_at_unix_seconds": int(observed_at_utc.timestamp()),
        "provider": OPEN_METEO_PROVIDER,
        "record_kind": OPEN_METEO_RECORD_KIND,
    }
    canonical_identity = json.dumps(identity, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical_identity.encode("utf-8")).hexdigest()
    return f"{OPEN_METEO_SOURCE_ID_PREFIX}:{digest}"


def normalize_open_meteo_coordinate(value: float) -> str:
    """Normalize provider coordinates to fixed six-decimal identity strings."""

    if isinstance(value, bool):
        raise ValueError("coordinates must not be booleans")
    decimal_value = Decimal(str(value)).quantize(
        OPEN_METEO_COORDINATE_PRECISION,
        rounding=ROUND_HALF_UP,
    )
    return format(decimal_value, "f")


def _validate_provider_response(payload: JsonObject) -> _OpenMeteoCurrentResponse:
    try:
        return _OpenMeteoCurrentResponse.model_validate(payload)
    except ValidationError as exc:
        raise ExternalSourcePayloadError(
            "Open-Meteo response failed provider contract validation",
            method="GET",
            safe_url=OPEN_METEO_FORECAST_ENDPOINT,
        ) from exc


def _require_utc_observation_time(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("observed_at must be timezone-aware")
    return value.astimezone(UTC)
