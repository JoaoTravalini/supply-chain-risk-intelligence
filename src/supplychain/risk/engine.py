"""Pure deterministic Supplier Risk Model v1 engine."""

from __future__ import annotations

import json
import math
from datetime import UTC, datetime
from typing import Final

from pydantic import ValidationError

from supplychain.contracts import (
    CanonicalEvent,
    EventType,
    SeismicEventPayload,
    WeatherObservationPayload,
)
from supplychain.domain import Criticality, Supplier
from supplychain.risk.models import (
    RiskFactorFamily,
    RiskModelConfig,
    StructuralRiskBreakdown,
    SupplierRiskAssessment,
    risk_level_for_score,
    round_risk_score,
)

EARTH_RADIUS_KM: Final = 6371.0088
DOMINANT_FACTOR_ORDER: Final = (
    RiskFactorFamily.STRUCTURAL,
    RiskFactorFamily.WEATHER,
    RiskFactorFamily.SEISMIC,
)


class SupplierRiskEngine:
    """Deterministic, side-effect-free Supplier Risk Model v1 calculator."""

    def __init__(self, config: RiskModelConfig | None = None) -> None:
        self._config = RiskModelConfig() if config is None else config

    @property
    def config(self) -> RiskModelConfig:
        """Return the immutable v1 model configuration."""

        return self._config

    def assess(
        self,
        supplier: Supplier,
        events: tuple[CanonicalEvent, ...],
        assessed_at: datetime,
    ) -> SupplierRiskAssessment:
        """Assess one supplier using only supplied inputs and explicit assessment time."""

        assessment_time = _require_aware_utc(assessed_at)
        structural, structural_score = self._structural_score(supplier)
        weather_score, weather_keys, weather_event_count = self._weather_score(
            supplier, events, assessment_time
        )
        seismic_score, seismic_keys, seismic_event_count = self._seismic_score(
            supplier, events, assessment_time
        )
        score = round_risk_score(
            self._config.overall_weight_structural * structural_score
            + self._config.overall_weight_weather * weather_score
            + self._config.overall_weight_seismic * seismic_score
        )
        evidence_keys = tuple(sorted(set(weather_keys) | set(seismic_keys)))
        return SupplierRiskAssessment(
            model_version=self._config.model_version,
            supplier_id=supplier.supplier_id,
            assessed_at=assessment_time,
            risk_score=score,
            risk_level=risk_level_for_score(score),
            structural_score=structural_score,
            weather_score=weather_score,
            seismic_score=seismic_score,
            structural=structural,
            relevant_weather_event_count=weather_event_count,
            relevant_seismic_event_count=seismic_event_count,
            evidence_deduplication_keys=evidence_keys,
            dominant_factor=self._dominant_factor(
                structural_score=structural_score,
                weather_score=weather_score,
                seismic_score=seismic_score,
            ),
        )

    def _structural_score(self, supplier: Supplier) -> tuple[StructuralRiskBreakdown, float]:
        criticality = {
            Criticality.LOW: self._config.criticality_low,
            Criticality.MEDIUM: self._config.criticality_medium,
            Criticality.HIGH: self._config.criticality_high,
            Criticality.CRITICAL: self._config.criticality_critical,
        }[supplier.criticality]
        breakdown = StructuralRiskBreakdown(
            criticality_component=criticality,
            dependency_component=supplier.dependency_score,
            single_source_component=1.0 if supplier.single_source else 0.0,
            lead_time_component=_clamp(supplier.typical_lead_time_days / 365),
        )
        score = 100 * (
            self._config.structural_weight_criticality * breakdown.criticality_component
            + self._config.structural_weight_dependency * breakdown.dependency_component
            + self._config.structural_weight_single_source * breakdown.single_source_component
            + self._config.structural_weight_lead_time * breakdown.lead_time_component
        )
        return breakdown, round_risk_score(score)

    def _weather_score(
        self,
        supplier: Supplier,
        events: tuple[CanonicalEvent, ...],
        assessed_at: datetime,
    ) -> tuple[float, tuple[str, ...], int]:
        hazards: list[float] = []
        evidence_keys: list[str] = []
        window_start = assessed_at - self._config.weather_lookback
        for event in events:
            if event.event_type is not EventType.WEATHER_OBSERVATION_RECORDED:
                continue
            if not window_start <= event.event_time <= assessed_at:
                continue
            payload = _weather_payload(event)
            if not _weather_relevant(supplier, event, payload, self._config):
                continue
            hazards.append(self._weather_hazard(payload))
            evidence_keys.append(event.metadata.deduplication_key)
        return (
            round_risk_score(100 * max(hazards, default=0.0)),
            tuple(sorted(set(evidence_keys))),
            len(evidence_keys),
        )

    def _weather_hazard(self, payload: WeatherObservationPayload) -> float:
        return (
            self._config.weather_weight_wind_speed
            * _clamp(payload.wind_speed_10m_kmh / self._config.weather_wind_speed_threshold_kmh)
            + self._config.weather_weight_wind_gust
            * _clamp(payload.wind_gusts_10m_kmh / self._config.weather_wind_gust_threshold_kmh)
            + self._config.weather_weight_precipitation
            * _clamp(payload.precipitation_mm / self._config.weather_precipitation_threshold_mm)
            + self._config.weather_weight_snowfall
            * _clamp(payload.snowfall_cm / self._config.weather_snowfall_threshold_cm)
        )

    def _seismic_score(
        self,
        supplier: Supplier,
        events: tuple[CanonicalEvent, ...],
        assessed_at: datetime,
    ) -> tuple[float, tuple[str, ...], int]:
        hazards: list[float] = []
        evidence_keys: list[str] = []
        window_start = assessed_at - self._config.seismic_lookback
        for event in events:
            if event.event_type is not EventType.SEISMIC_EVENT_DETECTED:
                continue
            if not window_start <= event.event_time <= assessed_at:
                continue
            payload = _seismic_payload(event)
            distance = haversine_distance_km(
                supplier.location.latitude,
                supplier.location.longitude,
                payload.latitude,
                payload.longitude,
            )
            if distance > self._config.seismic_relevance_radius_km:
                continue
            hazards.append(self._seismic_hazard(payload, distance))
            evidence_keys.append(event.metadata.deduplication_key)
        return (
            round_risk_score(100 * max(hazards, default=0.0)),
            tuple(sorted(set(evidence_keys))),
            len(evidence_keys),
        )

    def _seismic_hazard(self, payload: SeismicEventPayload, distance_km: float) -> float:
        magnitude_factor = _clamp((payload.magnitude - 3.0) / 4.0)
        distance_factor = _clamp(1 - distance_km / self._config.seismic_relevance_radius_km)
        return magnitude_factor * distance_factor

    def _dominant_factor(
        self,
        *,
        structural_score: float,
        weather_score: float,
        seismic_score: float,
    ) -> RiskFactorFamily:
        contributions = {
            RiskFactorFamily.STRUCTURAL: structural_score * self._config.overall_weight_structural,
            RiskFactorFamily.WEATHER: weather_score * self._config.overall_weight_weather,
            RiskFactorFamily.SEISMIC: seismic_score * self._config.overall_weight_seismic,
        }
        return max(
            DOMINANT_FACTOR_ORDER,
            key=lambda factor: (contributions[factor], -DOMINANT_FACTOR_ORDER.index(factor)),
        )


def haversine_distance_km(
    first_latitude: float,
    first_longitude: float,
    second_latitude: float,
    second_longitude: float,
) -> float:
    """Return deterministic great-circle distance in kilometers."""

    first_lat = math.radians(first_latitude)
    second_lat = math.radians(second_latitude)
    delta_lat = math.radians(second_latitude - first_latitude)
    delta_lon = math.radians(second_longitude - first_longitude)
    haversine = (
        math.sin(delta_lat / 2) ** 2
        + math.cos(first_lat) * math.cos(second_lat) * math.sin(delta_lon / 2) ** 2
    )
    return EARTH_RADIUS_KM * 2 * math.atan2(math.sqrt(haversine), math.sqrt(1 - haversine))


def _weather_relevant(
    supplier: Supplier,
    event: CanonicalEvent,
    payload: WeatherObservationPayload,
    config: RiskModelConfig,
) -> bool:
    if (
        event.entity is not None
        and event.entity.type == "supplier"
        and event.entity.id == supplier.supplier_id
    ):
        return True
    distance = haversine_distance_km(
        supplier.location.latitude,
        supplier.location.longitude,
        payload.latitude,
        payload.longitude,
    )
    return distance <= config.weather_relevance_radius_km


def _weather_payload(event: CanonicalEvent) -> WeatherObservationPayload:
    try:
        return WeatherObservationPayload.model_validate_json(json.dumps(event.payload))
    except ValidationError as exc:
        raise ValueError("weather event payload does not match WeatherObservationPayload") from exc


def _seismic_payload(event: CanonicalEvent) -> SeismicEventPayload:
    try:
        return SeismicEventPayload.model_validate_json(json.dumps(event.payload))
    except ValidationError as exc:
        raise ValueError("seismic event payload does not match SeismicEventPayload") from exc


def _require_aware_utc(value: datetime) -> datetime:
    if value.tzinfo is None or value.utcoffset() is None:
        raise ValueError("assessed_at must be timezone-aware")
    return value.astimezone(UTC)


def _clamp(value: float) -> float:
    return min(max(value, 0.0), 1.0)
