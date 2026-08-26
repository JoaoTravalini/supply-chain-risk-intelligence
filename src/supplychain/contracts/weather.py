"""Canonical weather observation payload contract."""

from __future__ import annotations

from typing import Annotated

from pydantic import BaseModel, ConfigDict, Field, field_validator

Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]
RelativeHumidityPct = Annotated[float, Field(ge=0.0, le=100.0)]
NonNegativeMeasurement = Annotated[float, Field(ge=0.0)]
WmoWeatherCode = Annotated[int, Field(ge=0, le=99)]


class StrictWeatherContractModel(BaseModel):
    """Base for immutable, strict weather payload models."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class WeatherObservationPayload(StrictWeatherContractModel):
    """Provider-independent canonical weather observation payload."""

    latitude: Latitude
    longitude: Longitude
    temperature_2m_c: float
    relative_humidity_2m_pct: RelativeHumidityPct
    precipitation_mm: NonNegativeMeasurement
    rain_mm: NonNegativeMeasurement
    snowfall_cm: NonNegativeMeasurement
    weather_code: WmoWeatherCode
    wind_speed_10m_kmh: NonNegativeMeasurement
    wind_gusts_10m_kmh: NonNegativeMeasurement

    @field_validator(
        "latitude",
        "longitude",
        "temperature_2m_c",
        "relative_humidity_2m_pct",
        "precipitation_mm",
        "rain_mm",
        "snowfall_cm",
        "wind_speed_10m_kmh",
        "wind_gusts_10m_kmh",
        mode="before",
    )
    @classmethod
    def reject_boolean_float_inputs(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("numeric weather measurements must not be booleans")
        return value

    @field_validator("weather_code", mode="before")
    @classmethod
    def reject_boolean_weather_code(cls, value: object) -> object:
        if isinstance(value, bool):
            raise ValueError("weather_code must be an integer WMO weather code")
        return value
