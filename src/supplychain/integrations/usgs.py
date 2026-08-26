"""USGS seismic event adapter."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal, cast

from pydantic import BaseModel, ConfigDict, Field, JsonValue, ValidationError, field_validator

from supplychain.contracts import (
    CanonicalEvent,
    EntityReference,
    EventMetadata,
    EventType,
    SeismicEventPayload,
    SourceMetadata,
    generate_deduplication_key,
)
from supplychain.integrations.errors import ExternalSourcePayloadError
from supplychain.integrations.http import ExternalHttpClient, JsonObject

USGS_QUERY_ENDPOINT = "https://earthquake.usgs.gov/fdsnws/event/1/query"
USGS_PROVIDER = "usgs"
USGS_PRODUCER = "usgs-seismic-adapter"
USGS_PRODUCER_VERSION = "1.0.0"
USGS_DEFAULT_LIMIT = 100
USGS_MAX_LIMIT = 500
USGS_MAX_RADIUS_KM = 1000.0

CoordinateLatitude = Annotated[float, Field(ge=-90.0, le=90.0)]
CoordinateLongitude = Annotated[float, Field(ge=-180.0, le=180.0)]
RadiusKm = Annotated[float, Field(gt=0.0, le=USGS_MAX_RADIUS_KM)]
MinimumMagnitude = Annotated[float, Field(ge=0.0)]
ResultLimit = Annotated[int, Field(ge=1, le=USGS_MAX_LIMIT)]
DepthKm = Annotated[float, Field(ge=-100.0, le=1000.0)]
ProviderMagnitude = Annotated[float, Field(ge=-10.0, le=10.0)]
Significance = Annotated[int, Field(ge=0)]


class _ProviderModel(BaseModel):
    model_config = ConfigDict(extra="allow", frozen=True, strict=True)


class _UsgsQuery(_ProviderModel):
    latitude: CoordinateLatitude
    longitude: CoordinateLongitude
    start_time: datetime
    end_time: datetime
    max_radius_km: RadiusKm
    min_magnitude: MinimumMagnitude
    limit: ResultLimit = USGS_DEFAULT_LIMIT

    @field_validator("latitude", "longitude", "max_radius_km", "min_magnitude", mode="before")
    @classmethod
    def reject_boolean_float_inputs(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("USGS query numeric values must not be booleans")
        return value

    @field_validator("limit", mode="before")
    @classmethod
    def reject_boolean_limit(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("USGS query limit must not be a boolean")
        return value

    @field_validator("start_time", "end_time")
    @classmethod
    def normalize_aware_datetimes(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("USGS query datetimes must be timezone-aware")
        return value.astimezone(UTC)

    @field_validator("end_time")
    @classmethod
    def require_ordered_time_window(cls, value: datetime, info: object) -> datetime:
        data = getattr(info, "data", {})
        start_time = data.get("start_time")
        if isinstance(start_time, datetime) and start_time >= value:
            raise ValueError("start_time must be before end_time")
        return value


class _UsgsMetadata(_ProviderModel):
    status: int
    count: int | None = None

    @field_validator("status", "count", mode="before")
    @classmethod
    def reject_boolean_metadata_integers(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, bool):
            raise ValueError("USGS metadata integer fields must not be booleans")
        return value


class _UsgsGeometry(_ProviderModel):
    type: Literal["Point"]
    coordinates: tuple[CoordinateLongitude, CoordinateLatitude, DepthKm]

    @field_validator("coordinates", mode="before")
    @classmethod
    def reject_malformed_coordinates(cls, value: object) -> object:
        if not isinstance(value, list | tuple) or len(value) != 3:
            raise ValueError("USGS Point coordinates must contain longitude, latitude, depth")
        if any(isinstance(item, bool) for item in value):
            raise ValueError("USGS Point coordinates must not contain booleans")
        return tuple(value)


class _UsgsProperties(_ProviderModel):
    mag: ProviderMagnitude
    place: Annotated[str, Field(min_length=1)]
    time: int
    updated: int
    status: Literal["automatic", "reviewed"]
    tsunami: Literal[0, 1]
    sig: Significance
    magType: Annotated[str, Field(min_length=1)] | None = None
    type: Literal["earthquake"]

    @field_validator("mag", mode="before")
    @classmethod
    def reject_boolean_magnitude(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("USGS magnitude must not be a boolean")
        return value

    @field_validator("time", "updated", "sig", "tsunami", mode="before")
    @classmethod
    def reject_boolean_integer_properties(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("USGS integer properties must not be booleans")
        return value

    @field_validator("place", "magType", mode="before")
    @classmethod
    def reject_blank_strings(cls, value: object) -> object:
        if value is None:
            return value
        if isinstance(value, str) and not value.strip():
            raise ValueError("USGS string properties must not be blank")
        return value


class _UsgsFeature(_ProviderModel):
    type: Literal["Feature"]
    id: Annotated[str, Field(min_length=1)]
    properties: _UsgsProperties
    geometry: _UsgsGeometry

    @field_validator("id", mode="before")
    @classmethod
    def reject_blank_id(cls, value: object) -> object:
        if isinstance(value, str) and not value.strip():
            raise ValueError("USGS feature id must not be blank")
        return value


class _UsgsFeatureCollection(_ProviderModel):
    type: Literal["FeatureCollection"]
    metadata: _UsgsMetadata
    features: tuple[_UsgsFeature, ...]

    @field_validator("features", mode="before")
    @classmethod
    def normalize_feature_array(cls, value: object) -> object:
        if not isinstance(value, list | tuple):
            raise ValueError("USGS FeatureCollection features must be an array")
        return tuple(value)


class UsgsSeismicAdapter:
    """Fetch nearby USGS earthquake events and canonicalize them."""

    def __init__(self, http_client: ExternalHttpClient) -> None:
        self._http_client = http_client

    def fetch_nearby_events(
        self,
        *,
        latitude: float,
        longitude: float,
        start_time: datetime,
        end_time: datetime,
        max_radius_km: float,
        min_magnitude: float = 0.0,
        limit: int = USGS_DEFAULT_LIMIT,
        correlation_id: str,
        entity: EntityReference | None = None,
        ingested_at: datetime | None = None,
    ) -> tuple[CanonicalEvent, ...]:
        """Fetch nearby earthquake events from USGS and return Canonical Events."""

        query = _UsgsQuery.model_validate(
            {
                "latitude": latitude,
                "longitude": longitude,
                "start_time": start_time,
                "end_time": end_time,
                "max_radius_km": max_radius_km,
                "min_magnitude": min_magnitude,
                "limit": limit,
            }
        )
        provider_payload = self._http_client.get_json_object(
            USGS_QUERY_ENDPOINT,
            params={
                "format": "geojson",
                "eventtype": "earthquake",
                "latitude": query.latitude,
                "longitude": query.longitude,
                "maxradiuskm": query.max_radius_km,
                "starttime": format_usgs_datetime(query.start_time),
                "endtime": format_usgs_datetime(query.end_time),
                "minmagnitude": query.min_magnitude,
                "limit": query.limit,
                "orderby": "time-asc",
            },
        )
        response = _validate_provider_response(provider_payload)
        return tuple(
            _canonicalize_feature(
                feature=feature,
                correlation_id=correlation_id,
                entity=entity,
                ingested_at=ingested_at,
            )
            for feature in response.features
        )


def format_usgs_datetime(value: datetime) -> str:
    """Serialize an aware datetime as explicit UTC ISO-8601 for USGS."""

    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("USGS query datetime must be timezone-aware")
    return value.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _canonicalize_feature(
    *,
    feature: _UsgsFeature,
    correlation_id: str,
    entity: EntityReference | None,
    ingested_at: datetime | None,
) -> CanonicalEvent:
    longitude, latitude, depth_km = feature.geometry.coordinates
    event_time = _datetime_from_epoch_millis(feature.properties.time)
    source_updated_at = _datetime_from_epoch_millis(feature.properties.updated)
    payload = SeismicEventPayload(
        latitude=latitude,
        longitude=longitude,
        depth_km=depth_km,
        magnitude=feature.properties.mag,
        magnitude_type=feature.properties.magType,
        place=feature.properties.place,
        status=feature.properties.status,
        tsunami=feature.properties.tsunami == 1,
        significance=feature.properties.sig,
        source_updated_at=source_updated_at,
    )
    source = SourceMetadata(
        provider=USGS_PROVIDER,
        endpoint=USGS_QUERY_ENDPOINT,
        source_event_id=feature.id,
    )
    deduplication_key = generate_deduplication_key(
        source=source,
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=event_time,
    )
    event_data: dict[str, object] = {
        "event_type": EventType.SEISMIC_EVENT_DETECTED,
        "event_time": event_time,
        "source": source,
        "entity": entity,
        "location": None,
        "payload": cast(dict[str, JsonValue], payload.model_dump(mode="json")),
        "metadata": EventMetadata(
            correlation_id=correlation_id,
            producer=USGS_PRODUCER,
            producer_version=USGS_PRODUCER_VERSION,
            deduplication_key=deduplication_key,
        ),
    }
    if ingested_at is not None:
        event_data["ingested_at"] = ingested_at
    return CanonicalEvent.model_validate(event_data)


def _validate_provider_response(payload: JsonObject) -> _UsgsFeatureCollection:
    try:
        return _UsgsFeatureCollection.model_validate(payload)
    except ValidationError as exc:
        raise ExternalSourcePayloadError(
            "USGS GeoJSON response failed provider contract validation",
            method="GET",
            safe_url=USGS_QUERY_ENDPOINT,
        ) from exc


def _datetime_from_epoch_millis(value: int) -> datetime:
    if isinstance(value, bool):
        raise ValueError("epoch milliseconds must not be a boolean")
    return datetime.fromtimestamp(value / 1000, UTC)
