from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import cast
from uuid import UUID

import pytest
from pydantic import JsonValue, ValidationError

from supplychain.contracts import (
    CanonicalEvent,
    EntityReference,
    EventMetadata,
    EventType,
    LocationMetadata,
    SeismicEventPayload,
    SourceMetadata,
    WeatherObservationPayload,
    generate_deduplication_key,
)
from supplychain.domain import Criticality, Supplier, SupplierCategory, SupplierLocation
from supplychain.risk import (
    RISK_MODEL_VERSION,
    RiskFactorFamily,
    RiskLevel,
    RiskModelConfig,
    SupplierRiskAssessment,
    SupplierRiskEngine,
    haversine_distance_km,
    risk_level_for_score,
    round_risk_score,
)

SCHEMA_PATH = Path("schemas/risk/supplier-risk-assessment-v1.schema.json")
ASSESSED_AT = datetime(2026, 8, 28, 12, 0, tzinfo=UTC)


def make_supplier(**overrides: object) -> Supplier:
    data: dict[str, object] = {
        "supplier_id": "SUP-000001",
        "name": "Synthetic Components North",
        "category": SupplierCategory.ELECTRONIC_COMPONENTS,
        "criticality": Criticality.HIGH,
        "location": SupplierLocation(
            country_code="US",
            region="WA",
            city="Seattle",
            latitude=47.6062,
            longitude=-122.3321,
        ),
        "annual_spend_usd": 1_250_000,
        "typical_lead_time_days": 28,
        "dependency_score": 0.74,
        "single_source": True,
    }
    data.update(overrides)
    return Supplier.model_validate(data)


def make_event(
    *,
    event_type: EventType,
    event_time: datetime,
    source_event_id: str,
    payload: dict[str, JsonValue],
    entity: EntityReference | None = None,
) -> CanonicalEvent:
    source = SourceMetadata(
        provider="synthetic-risk",
        endpoint="synthetic://risk",
        source_event_id=source_event_id,
        request_id="request-risk-001",
    )
    deduplication_key = generate_deduplication_key(
        source=source,
        event_type=event_type,
        event_time=event_time,
    )
    return CanonicalEvent(
        event_id=UUID(int=abs(hash(source_event_id)) % (2**128)),
        event_type=event_type,
        event_time=event_time,
        ingested_at=event_time + timedelta(minutes=1),
        source=source,
        entity=entity,
        location=LocationMetadata(country_code="US", region="WA"),
        payload=payload,
        metadata=EventMetadata(
            correlation_id=f"corr-{source_event_id}",
            producer="risk-test",
            producer_version="1.0.0",
            deduplication_key=deduplication_key,
        ),
    )


def weather_payload(**overrides: object) -> dict[str, JsonValue]:
    data: dict[str, object] = {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "temperature_2m_c": 18.4,
        "relative_humidity_2m_pct": 73.0,
        "precipitation_mm": 0.0,
        "rain_mm": 0.0,
        "snowfall_cm": 0.0,
        "weather_code": 3,
        "wind_speed_10m_kmh": 0.0,
        "wind_gusts_10m_kmh": 0.0,
    }
    data.update(overrides)
    return cast(
        dict[str, JsonValue],
        WeatherObservationPayload.model_validate(data).model_dump(mode="json"),
    )


def seismic_payload(**overrides: object) -> dict[str, JsonValue]:
    data: dict[str, object] = {
        "latitude": 47.6062,
        "longitude": -122.3321,
        "depth_km": 8.0,
        "magnitude": 3.0,
        "magnitude_type": "mw",
        "place": "Synthetic epicenter",
        "status": "reviewed",
        "tsunami": False,
        "significance": 100,
        "source_updated_at": ASSESSED_AT,
    }
    data.update(overrides)
    return cast(
        dict[str, JsonValue], SeismicEventPayload.model_validate(data).model_dump(mode="json")
    )


def assess(
    supplier: Supplier | None = None,
    events: tuple[CanonicalEvent, ...] = (),
    assessed_at: datetime = ASSESSED_AT,
) -> SupplierRiskAssessment:
    return SupplierRiskEngine().assess(supplier or make_supplier(), events, assessed_at)


def test_risk_assessment_schema_artifact_matches_model() -> None:
    generated_schema = SupplierRiskAssessment.model_json_schema()
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == generated_schema


def test_same_input_produces_same_output_and_no_hidden_current_time() -> None:
    supplier = make_supplier()
    event = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-001",
        payload=weather_payload(wind_gusts_10m_kmh=70),
    )

    first = assess(supplier, (event,), ASSESSED_AT)
    second = assess(supplier, (event,), ASSESSED_AT)

    assert first == second


def test_structural_component_formula() -> None:
    result = assess()

    assert result.structural.criticality_component == 0.75
    assert result.structural.dependency_component == 0.74
    assert result.structural.single_source_component == 1.0
    assert result.structural.lead_time_component == pytest.approx(28 / 365)
    assert result.structural_score == 69.55


@pytest.mark.parametrize(
    ("criticality", "component"),
    [
        (Criticality.LOW, 0.25),
        (Criticality.MEDIUM, 0.50),
        (Criticality.HIGH, 0.75),
        (Criticality.CRITICAL, 1.00),
    ],
)
def test_criticality_mapping(criticality: Criticality, component: float) -> None:
    result = assess(make_supplier(criticality=criticality))

    assert result.structural.criticality_component == component


def test_dependency_single_source_and_lead_time_effects() -> None:
    low = assess(make_supplier(dependency_score=0.0, single_source=False, typical_lead_time_days=1))
    high = assess(
        make_supplier(dependency_score=1.0, single_source=True, typical_lead_time_days=365)
    )

    assert low.structural_score < high.structural_score
    assert low.structural.lead_time_component == pytest.approx(1 / 365)
    assert high.structural.lead_time_component == 1.0


def test_structural_weights_sum_to_one() -> None:
    config = RiskModelConfig()

    assert (
        config.structural_weight_criticality
        + config.structural_weight_dependency
        + config.structural_weight_single_source
        + config.structural_weight_lead_time
    ) == pytest.approx(1.0)


def test_weather_normalization_boundaries_and_max_observation_behavior() -> None:
    mild = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-mild",
        payload=weather_payload(wind_speed_10m_kmh=50),
    )
    severe = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-severe",
        payload=weather_payload(
            wind_speed_10m_kmh=120,
            wind_gusts_10m_kmh=200,
            precipitation_mm=60,
            snowfall_cm=40,
        ),
    )

    result = assess(events=(mild, severe))

    assert result.weather_score == 100.0
    assert result.relevant_weather_event_count == 2


def test_weather_radius_inclusion_exclusion_and_entity_association() -> None:
    nearby = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-near",
        payload=weather_payload(latitude=47.7, longitude=-122.3, wind_gusts_10m_kmh=70),
    )
    far = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-far",
        payload=weather_payload(latitude=40.7128, longitude=-74.0060, wind_gusts_10m_kmh=140),
    )
    linked_far = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-linked",
        payload=weather_payload(latitude=40.7128, longitude=-74.0060, wind_gusts_10m_kmh=140),
        entity=EntityReference(type="supplier", id="SUP-000001"),
    )

    radius_result = assess(events=(nearby, far))
    linked_result = assess(events=(far, linked_far))

    assert radius_result.weather_score == 17.5
    assert linked_result.weather_score == 35.0


def test_weather_lookback_boundaries_and_future_event_ignored() -> None:
    included = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT - timedelta(hours=24),
        source_event_id="weather-included",
        payload=weather_payload(wind_gusts_10m_kmh=140),
    )
    excluded = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT - timedelta(hours=24, seconds=1),
        source_event_id="weather-excluded",
        payload=weather_payload(wind_gusts_10m_kmh=140),
    )
    future = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT + timedelta(seconds=1),
        source_event_id="weather-future",
        payload=weather_payload(wind_gusts_10m_kmh=140),
    )

    result = assess(events=(included, excluded, future))

    assert result.weather_score == 35.0
    assert result.relevant_weather_event_count == 1


def test_seismic_magnitude_distance_radius_and_max_event_behavior() -> None:
    low = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT,
        source_event_id="seismic-low",
        payload=seismic_payload(magnitude=5.0),
    )
    high = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT,
        source_event_id="seismic-high",
        payload=seismic_payload(magnitude=7.5),
    )
    far = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT,
        source_event_id="seismic-far",
        payload=seismic_payload(latitude=0.0, longitude=0.0, magnitude=7.5),
    )

    result = assess(events=(low, high, far))

    assert result.seismic_score == 100.0
    assert result.relevant_seismic_event_count == 2


def test_seismic_lookback_boundaries() -> None:
    included = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT - timedelta(days=7),
        source_event_id="seismic-included",
        payload=seismic_payload(magnitude=7.0),
    )
    excluded = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT - timedelta(days=7, seconds=1),
        source_event_id="seismic-excluded",
        payload=seismic_payload(magnitude=7.0),
    )

    result = assess(events=(included, excluded))

    assert result.seismic_score == 100.0
    assert result.relevant_seismic_event_count == 1


def test_unrelated_event_type_does_not_influence_weather_or_seismic() -> None:
    event = make_event(
        event_type=EventType.SUPPLIER_OPERATIONAL_SNAPSHOT_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="operational-001",
        payload={"status": "disrupted"},
    )

    result = assess(events=(event,))

    assert result.weather_score == 0.0
    assert result.seismic_score == 0.0


def test_overall_weights_sum_to_one_and_score_uses_family_weights() -> None:
    config = RiskModelConfig()
    weather = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-strong",
        payload=weather_payload(wind_speed_10m_kmh=100),
    )
    result = assess(events=(weather,))

    assert (
        config.overall_weight_structural
        + config.overall_weight_weather
        + config.overall_weight_seismic
    ) == 1.0
    assert result.risk_score == 42.28


@pytest.mark.parametrize(
    ("score", "level"),
    [
        (0.0, RiskLevel.LOW),
        (24.99, RiskLevel.LOW),
        (25.0, RiskLevel.MEDIUM),
        (49.99, RiskLevel.MEDIUM),
        (50.0, RiskLevel.HIGH),
        (74.99, RiskLevel.HIGH),
        (75.0, RiskLevel.CRITICAL),
        (100.0, RiskLevel.CRITICAL),
    ],
)
def test_risk_level_exact_thresholds(score: float, level: RiskLevel) -> None:
    assert risk_level_for_score(score) is level


def test_deterministic_rounding() -> None:
    assert round_risk_score(12.345) == 12.35
    assert round_risk_score(12.344) == 12.34


def test_evidence_deduplication_and_deterministic_ordering() -> None:
    first = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-b",
        payload=weather_payload(wind_gusts_10m_kmh=140),
    )
    duplicate = CanonicalEvent.model_validate({**first.model_dump(), "event_id": UUID(int=999)})
    second = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT,
        source_event_id="seismic-a",
        payload=seismic_payload(magnitude=7.0),
    )

    result = assess(events=(first, duplicate, second))

    assert result.evidence_deduplication_keys == tuple(
        sorted({first.metadata.deduplication_key, second.metadata.deduplication_key})
    )


def test_dominant_factor_uses_weighted_contribution_with_tie_order() -> None:
    config = RiskModelConfig(
        overall_weight_structural=0.0,
        overall_weight_weather=0.5,
        overall_weight_seismic=0.5,
    )
    engine = SupplierRiskEngine(config)
    weather = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-max",
        payload=weather_payload(
            wind_speed_10m_kmh=100,
            wind_gusts_10m_kmh=140,
            precipitation_mm=50,
            snowfall_cm=30,
        ),
    )
    seismic = make_event(
        event_type=EventType.SEISMIC_EVENT_DETECTED,
        event_time=ASSESSED_AT,
        source_event_id="seismic-max",
        payload=seismic_payload(magnitude=7.0),
    )

    result = engine.assess(make_supplier(), (seismic, weather), ASSESSED_AT)

    assert result.dominant_factor is RiskFactorFamily.WEATHER


def test_invalid_typed_payload_fails_explicitly() -> None:
    event = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-invalid",
        payload=cast(dict[str, JsonValue], {"latitude": True}),
    )

    with pytest.raises(ValueError, match="WeatherObservationPayload"):
        assess(events=(event,))


def test_pure_engine_rejects_naive_assessed_at() -> None:
    with pytest.raises(ValueError, match="assessed_at"):
        assess(assessed_at=datetime(2026, 8, 28, 12, 0))


def test_risk_assessment_contract_is_strict_and_immutable() -> None:
    result = assess()
    with pytest.raises(ValidationError):
        SupplierRiskAssessment.model_validate({**result.model_dump(), "extra": "nope"})
    with pytest.raises(ValidationError):
        result.risk_score = 99.0


def test_haversine_same_point_is_zero_and_known_distance() -> None:
    assert haversine_distance_km(47.6062, -122.3321, 47.6062, -122.3321) == pytest.approx(0.0)
    assert haversine_distance_km(47.6062, -122.3321, 45.5152, -122.6784) == pytest.approx(
        234.0,
        abs=2.0,
    )


def test_haversine_radius_boundary_is_inclusive() -> None:
    supplier = make_supplier()
    config = RiskModelConfig(weather_relevance_radius_km=12.0)
    engine = SupplierRiskEngine(config)
    near = make_event(
        event_type=EventType.WEATHER_OBSERVATION_RECORDED,
        event_time=ASSESSED_AT,
        source_event_id="weather-radius-near",
        payload=weather_payload(latitude=47.714, longitude=-122.3321, wind_gusts_10m_kmh=140),
    )

    result = engine.assess(supplier, (near,), ASSESSED_AT)

    assert result.weather_score == 35.0


def test_engine_performs_no_network_or_database_access(monkeypatch: pytest.MonkeyPatch) -> None:
    def fail(*args: object, **kwargs: object) -> None:
        raise AssertionError("network/database access is not allowed")

    monkeypatch.setattr("socket.create_connection", fail)
    assert assess().model_version == RISK_MODEL_VERSION
