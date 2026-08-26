"""Canonical seismic event payload contract."""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
DepthKm = Annotated[float, Field(ge=-100.0, le=1000.0)]
Magnitude = Annotated[float, Field(ge=-10.0, le=10.0)]
NonEmptyString = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, strict=True)]
ReviewStatus = Literal["automatic", "reviewed"]
Significance = Annotated[int, Field(ge=0)]


class StrictSeismicContractModel(BaseModel):
    """Base for immutable, strict seismic payload models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SeismicEventPayload(StrictSeismicContractModel):
    """Provider-independent canonical seismic event payload."""

    latitude: Latitude
    longitude: Longitude
    depth_km: DepthKm
    magnitude: Magnitude
    magnitude_type: NonEmptyString | None = None
    place: NonEmptyString
    status: ReviewStatus
    tsunami: bool
    significance: Significance
    source_updated_at: datetime

    @field_validator(
        "latitude",
        "longitude",
        "depth_km",
        "magnitude",
        mode="before",
    )
    @classmethod
    def reject_boolean_float_inputs(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("numeric seismic measurements must not be booleans")
        return value

    @field_validator("significance", mode="before")
    @classmethod
    def reject_boolean_significance(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("significance must be an integer")
        return value

    @field_validator("source_updated_at")
    @classmethod
    def require_aware_utc_source_updated_at(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("source_updated_at must be timezone-aware")
        return value.astimezone(UTC)
