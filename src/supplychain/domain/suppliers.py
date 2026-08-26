"""Supplier master-data domain contract."""

from __future__ import annotations

import re
from enum import StrEnum
from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, StringConstraints

SUPPLIER_SCHEMA_VERSION: Literal["1.0.0"] = "1.0.0"

SupplierId = Annotated[
    str,
    StringConstraints(pattern=r"^SUP-\d{6}$", strict=True),
]
NonEmptyString = Annotated[
    str,
    StringConstraints(strip_whitespace=True, min_length=1, max_length=120, strict=True),
]
CountryCode = Annotated[str, StringConstraints(pattern=r"^[A-Z]{2}$", strict=True)]
PositiveWholeDollars = Annotated[int, Field(gt=0)]
LeadTimeDays = Annotated[int, Field(gt=0, le=365)]
DependencyScore = Annotated[float, Field(ge=0.0, le=1.0)]
Latitude = Annotated[float, Field(ge=-90.0, le=90.0)]
Longitude = Annotated[float, Field(ge=-180.0, le=180.0)]


class StrictDomainModel(BaseModel):
    """Base for immutable, strict domain contracts."""

    model_config = ConfigDict(extra="forbid", frozen=True, strict=True)


class SupplierCategory(StrEnum):
    """Approved Stage 7A supplier category taxonomy."""

    SEMICONDUCTORS = "semiconductors"
    ELECTRONIC_COMPONENTS = "electronic_components"
    AUTOMOTIVE_COMPONENTS = "automotive_components"
    INDUSTRIAL_EQUIPMENT = "industrial_equipment"
    METALS = "metals"
    CHEMICALS = "chemicals"
    PACKAGING = "packaging"
    LOGISTICS = "logistics"


class Criticality(StrEnum):
    """Operational impact if the supplier becomes unavailable."""

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


class SupplierLocation(StrictDomainModel):
    """Stable supplier location used for future risk correlation."""

    country_code: CountryCode
    region: NonEmptyString
    city: NonEmptyString
    latitude: Latitude
    longitude: Longitude


class Supplier(StrictDomainModel):
    """Immutable canonical supplier master-data contract."""

    schema_version: Literal["1.0.0"] = SUPPLIER_SCHEMA_VERSION
    supplier_id: SupplierId
    name: NonEmptyString
    category: SupplierCategory
    criticality: Criticality
    location: SupplierLocation
    annual_spend_usd: PositiveWholeDollars
    typical_lead_time_days: LeadTimeDays
    dependency_score: DependencyScore
    single_source: bool


assert re.fullmatch(
    r"^(0|[1-9]\d*)\.(0|[1-9]\d*)\.(0|[1-9]\d*)(?:[-+][0-9A-Za-z.-]+)?$",
    SUPPLIER_SCHEMA_VERSION,
)
