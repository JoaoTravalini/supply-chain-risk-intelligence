"""Versioned deterministic supplier risk assessment contracts."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from decimal import ROUND_HALF_UP, Decimal
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, field_validator

RISK_MODEL_VERSION: Literal["1.0.0"] = "1.0.0"

SupplierId = Annotated[str, StringConstraints(pattern=r"^SUP-\d{6}$", strict=True)]
SemanticVersion = Annotated[
    str,
    StringConstraints(
        pattern=r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)$",
        strict=True,
    ),
]
RiskScore = Annotated[float, Field(ge=0.0, le=100.0)]
ComponentScore = Annotated[float, Field(ge=0.0, le=1.0)]
EvidenceKey = Annotated[str, StringConstraints(pattern=r"^[0-9a-f]{64}$", strict=True)]


class RiskLevel(StrEnum):
    """Approved v1 risk levels."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class RiskFactorFamily(StrEnum):
    """Risk factor families calculated by model v1."""

    STRUCTURAL = "STRUCTURAL"
    WEATHER = "WEATHER"
    SEISMIC = "SEISMIC"


class StrictRiskModel(BaseModel):
    """Base for immutable, strict risk contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class StructuralRiskBreakdown(StrictRiskModel):
    """Normalized 0..1 structural factor components."""

    criticality_component: ComponentScore
    dependency_component: ComponentScore
    single_source_component: ComponentScore
    lead_time_component: ComponentScore


class SupplierRiskAssessment(StrictRiskModel):
    """Deterministic Supplier Risk Model v1 assessment output."""

    model_version: SemanticVersion = RISK_MODEL_VERSION
    supplier_id: SupplierId
    assessed_at: datetime
    risk_score: RiskScore
    risk_level: RiskLevel
    structural_score: RiskScore
    weather_score: RiskScore
    seismic_score: RiskScore
    structural: StructuralRiskBreakdown
    relevant_weather_event_count: int = Field(ge=0)
    relevant_seismic_event_count: int = Field(ge=0)
    evidence_deduplication_keys: tuple[EvidenceKey, ...]
    dominant_factor: RiskFactorFamily

    @field_validator("assessed_at")
    @classmethod
    def require_aware_utc(cls, value: datetime) -> datetime:
        if value.tzinfo is None or value.utcoffset() is None:
            raise ValueError("assessed_at must be timezone-aware")
        return value.astimezone(UTC)


@dataclass(frozen=True, slots=True)
class RiskModelConfig:
    """Explicit immutable constants for Supplier Risk Model v1."""

    model_version: str = RISK_MODEL_VERSION
    criticality_low: float = 0.25
    criticality_medium: float = 0.50
    criticality_high: float = 0.75
    criticality_critical: float = 1.00
    structural_weight_criticality: float = 0.30
    structural_weight_dependency: float = 0.35
    structural_weight_single_source: float = 0.20
    structural_weight_lead_time: float = 0.15
    weather_lookback: timedelta = timedelta(hours=24)
    weather_relevance_radius_km: float = 50.0
    weather_wind_speed_threshold_kmh: float = 100.0
    weather_wind_gust_threshold_kmh: float = 140.0
    weather_precipitation_threshold_mm: float = 50.0
    weather_snowfall_threshold_cm: float = 30.0
    weather_weight_wind_speed: float = 0.25
    weather_weight_wind_gust: float = 0.35
    weather_weight_precipitation: float = 0.25
    weather_weight_snowfall: float = 0.15
    seismic_lookback: timedelta = timedelta(days=7)
    seismic_relevance_radius_km: float = 1000.0
    overall_weight_structural: float = 0.50
    overall_weight_weather: float = 0.30
    overall_weight_seismic: float = 0.20
    low_threshold: float = 0.0
    medium_threshold: float = 25.0
    high_threshold: float = 50.0
    critical_threshold: float = 75.0
    maximum_score: float = 100.0

    def __post_init__(self) -> None:
        _require_sum_to_one(
            self.structural_weight_criticality,
            self.structural_weight_dependency,
            self.structural_weight_single_source,
            self.structural_weight_lead_time,
        )
        _require_sum_to_one(
            self.weather_weight_wind_speed,
            self.weather_weight_wind_gust,
            self.weather_weight_precipitation,
            self.weather_weight_snowfall,
        )
        _require_sum_to_one(
            self.overall_weight_structural,
            self.overall_weight_weather,
            self.overall_weight_seismic,
        )
        if self.model_version != RISK_MODEL_VERSION:
            raise ValueError("Risk Model v1 config must use model_version 1.0.0")
        if self.weather_lookback <= timedelta(0) or self.seismic_lookback <= timedelta(0):
            raise ValueError("Risk lookback windows must be positive")
        if self.weather_relevance_radius_km <= 0 or self.seismic_relevance_radius_km <= 0:
            raise ValueError("Risk relevance radii must be positive")


def round_risk_score(value: float) -> float:
    """Round risk scores consistently to two decimal places."""

    rounded = Decimal(str(value)).quantize(Decimal("0.01"), rounding=ROUND_HALF_UP)
    return float(rounded)


def risk_level_for_score(score: float) -> RiskLevel:
    """Return the v1 risk level for a 0..100 score."""

    if not 0 <= score <= 100:
        raise ValueError("risk score must be between 0 and 100")
    if score < 25:
        return RiskLevel.LOW
    if score < 50:
        return RiskLevel.MEDIUM
    if score < 75:
        return RiskLevel.HIGH
    return RiskLevel.CRITICAL


def _require_sum_to_one(*values: float) -> None:
    if abs(sum(values) - 1.0) > 0.000_001:
        raise ValueError("risk weights must sum to 1.0")
