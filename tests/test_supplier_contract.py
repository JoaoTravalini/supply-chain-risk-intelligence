from __future__ import annotations

import json
from pathlib import Path

import pytest
from pydantic import ValidationError

from supplychain.domain import (
    SUPPLIER_SCHEMA_VERSION,
    Criticality,
    Supplier,
    SupplierCategory,
    SupplierLocation,
)

SCHEMA_PATH = Path("schemas/domain/supplier-v1.schema.json")


def make_location(**overrides: object) -> SupplierLocation:
    data: dict[str, object] = {
        "country_code": "US",
        "region": "WA",
        "city": "Seattle",
        "latitude": 47.6062,
        "longitude": -122.3321,
    }
    data.update(overrides)
    return SupplierLocation.model_validate(data)


def supplier_data(**overrides: object) -> dict[str, object]:
    data: dict[str, object] = {
        "supplier_id": "SUP-000001",
        "name": "Northstar Components",
        "category": SupplierCategory.ELECTRONIC_COMPONENTS,
        "criticality": Criticality.HIGH,
        "location": make_location(),
        "annual_spend_usd": 2_500_000,
        "typical_lead_time_days": 45,
        "dependency_score": 0.72,
        "single_source": False,
    }
    data.update(overrides)
    return data


def make_supplier(**overrides: object) -> Supplier:
    return Supplier.model_validate(supplier_data(**overrides))


def test_valid_supplier_construction() -> None:
    supplier = make_supplier()

    assert supplier.schema_version == SUPPLIER_SCHEMA_VERSION
    assert supplier.supplier_id == "SUP-000001"
    assert supplier.name == "Northstar Components"
    assert supplier.location.country_code == "US"


def test_public_supplier_import() -> None:
    assert Supplier.__name__ == "Supplier"
    assert SupplierCategory.SEMICONDUCTORS.value == "semiconductors"
    assert Criticality.CRITICAL.value == "CRITICAL"


def test_correct_schema_version() -> None:
    assert SUPPLIER_SCHEMA_VERSION == "1.0.0"
    assert make_supplier().schema_version == "1.0.0"


def test_invalid_schema_version_rejection() -> None:
    with pytest.raises(ValidationError):
        make_supplier(schema_version="1.1.0")


@pytest.mark.parametrize("supplier_id", ["SUP-000001", "SUP-123456"])
def test_valid_supplier_id(supplier_id: str) -> None:
    assert make_supplier(supplier_id=supplier_id).supplier_id == supplier_id


@pytest.mark.parametrize(
    "supplier_id",
    ["SUP-1", "supplier-000001", "sup-000001", "000001", "SUP-ABCDEF", "   "],
)
def test_malformed_supplier_ids_rejected(supplier_id: str) -> None:
    with pytest.raises(ValidationError):
        make_supplier(supplier_id=supplier_id)


def test_empty_supplier_name_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(name="   ")


def test_unknown_field_rejected() -> None:
    data = supplier_data()
    data["current_risk_score"] = 0.8

    with pytest.raises(ValidationError):
        Supplier.model_validate(data)


def test_unknown_category_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(category="textiles")


def test_unknown_criticality_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(criticality="SEVERE")


def test_invalid_lowercase_country_code_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(country_code="us")


def test_invalid_country_code_length_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(country_code="USA")


def test_empty_region_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(region="   ")


def test_empty_city_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(city="   ")


def test_latitude_below_minus_90_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(latitude=-90.0001)


def test_latitude_above_90_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(latitude=90.0001)


def test_longitude_below_minus_180_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(longitude=-180.0001)


def test_longitude_above_180_rejected() -> None:
    with pytest.raises(ValidationError):
        make_location(longitude=180.0001)


def test_zero_annual_spend_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(annual_spend_usd=0)


def test_negative_annual_spend_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(annual_spend_usd=-1)


@pytest.mark.parametrize("lead_time", [0, -1, 366])
def test_invalid_lead_time_rejected(lead_time: int) -> None:
    with pytest.raises(ValidationError):
        make_supplier(typical_lead_time_days=lead_time)


def test_dependency_score_below_0_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(dependency_score=-0.01)


def test_dependency_score_above_1_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(dependency_score=1.01)


def test_non_boolean_single_source_coercion_rejected() -> None:
    with pytest.raises(ValidationError):
        make_supplier(single_source="true")


@pytest.mark.parametrize(
    ("field", "value"),
    [
        ("annual_spend_usd", True),
        ("typical_lead_time_days", True),
        ("dependency_score", True),
    ],
)
def test_boolean_numeric_coercion_rejected(field: str, value: bool) -> None:
    with pytest.raises(ValidationError):
        make_supplier(**{field: value})


def test_model_immutability() -> None:
    supplier = make_supplier()

    with pytest.raises(ValidationError):
        supplier.name = "Mutated Supplier"


def test_supplier_json_schema_artifact_matches_model() -> None:
    generated_schema = Supplier.model_json_schema()
    committed_schema = json.loads(SCHEMA_PATH.read_text(encoding="utf-8"))

    assert committed_schema == generated_schema
