"""Deterministic synthetic Supplier master-data generation."""

from __future__ import annotations

import hashlib
import json
import random
from dataclasses import dataclass
from pathlib import Path

from supplychain.domain.suppliers import (
    SUPPLIER_SCHEMA_VERSION,
    Criticality,
    Supplier,
    SupplierCategory,
    SupplierLocation,
)

SUPPLIER_GENERATOR_VERSION = "1.0.0"
SUPPLIER_GENERATOR_SEED = 7407
SUPPLIER_RECORD_COUNT = 120
SUPPLIER_DATASET_NAME = "synthetic-suppliers-v1"
SUPPLIER_DATASET_PATH = Path("data/synthetic/suppliers-v1.jsonl")
SUPPLIER_MANIFEST_PATH = Path("data/synthetic/suppliers-v1.manifest.json")
SUPPLIER_SCHEMA_PATH = Path("schemas/domain/supplier-v1.schema.json")


@dataclass(frozen=True)
class SyntheticLocation:
    country_code: str
    region: str
    city: str
    latitude: float
    longitude: float


LOCATION_CATALOG: tuple[SyntheticLocation, ...] = (
    SyntheticLocation("US", "WA", "Seattle", 47.6062, -122.3321),
    SyntheticLocation("US", "TX", "Austin", 30.2672, -97.7431),
    SyntheticLocation("DE", "Bavaria", "Munich", 48.1351, 11.5820),
    SyntheticLocation("DE", "Baden-Wurttemberg", "Stuttgart", 48.7758, 9.1829),
    SyntheticLocation("BR", "Sao Paulo", "Campinas", -22.9099, -47.0626),
    SyntheticLocation("JP", "Aichi", "Nagoya", 35.1815, 136.9066),
    SyntheticLocation("CN", "Guangdong", "Shenzhen", 22.5431, 114.0579),
    SyntheticLocation("TW", "Hsinchu", "Hsinchu", 24.8138, 120.9675),
    SyntheticLocation("KR", "Gyeonggi", "Suwon", 37.2636, 127.0286),
    SyntheticLocation("MX", "Nuevo Leon", "Monterrey", 25.6866, -100.3161),
    SyntheticLocation("CA", "Ontario", "Toronto", 43.6532, -79.3832),
    SyntheticLocation("IN", "Karnataka", "Bengaluru", 12.9716, 77.5946),
    SyntheticLocation("VN", "Ho Chi Minh", "Ho Chi Minh City", 10.8231, 106.6297),
    SyntheticLocation("FR", "Auvergne-Rhone-Alpes", "Lyon", 45.7640, 4.8357),
    SyntheticLocation("IT", "Lombardy", "Milan", 45.4642, 9.1900),
    SyntheticLocation("PL", "Silesian", "Katowice", 50.2649, 19.0238),
    SyntheticLocation("CZ", "South Moravian", "Brno", 49.1951, 16.6068),
)

CATEGORY_LOCATION_COUNTRIES: dict[SupplierCategory, tuple[str, ...]] = {
    SupplierCategory.SEMICONDUCTORS: ("TW", "KR", "JP", "US", "CN"),
    SupplierCategory.ELECTRONIC_COMPONENTS: ("CN", "TW", "KR", "VN", "US", "MX"),
    SupplierCategory.AUTOMOTIVE_COMPONENTS: ("DE", "MX", "US", "CZ", "PL", "JP"),
    SupplierCategory.INDUSTRIAL_EQUIPMENT: ("DE", "US", "IT", "FR", "JP"),
    SupplierCategory.METALS: ("BR", "CN", "IN", "CA", "PL"),
    SupplierCategory.CHEMICALS: ("DE", "US", "CN", "IN", "FR"),
    SupplierCategory.PACKAGING: ("US", "MX", "VN", "PL", "BR"),
    SupplierCategory.LOGISTICS: ("US", "DE", "MX", "CA", "VN", "FR"),
}

SPEND_RANGES: dict[SupplierCategory, tuple[int, int]] = {
    SupplierCategory.SEMICONDUCTORS: (2_500_000, 18_000_000),
    SupplierCategory.ELECTRONIC_COMPONENTS: (750_000, 7_500_000),
    SupplierCategory.AUTOMOTIVE_COMPONENTS: (1_200_000, 9_000_000),
    SupplierCategory.INDUSTRIAL_EQUIPMENT: (1_500_000, 12_000_000),
    SupplierCategory.METALS: (900_000, 8_500_000),
    SupplierCategory.CHEMICALS: (700_000, 6_500_000),
    SupplierCategory.PACKAGING: (250_000, 2_800_000),
    SupplierCategory.LOGISTICS: (400_000, 4_500_000),
}

LEAD_TIME_RANGES: dict[SupplierCategory, tuple[int, int]] = {
    SupplierCategory.SEMICONDUCTORS: (45, 140),
    SupplierCategory.ELECTRONIC_COMPONENTS: (21, 90),
    SupplierCategory.AUTOMOTIVE_COMPONENTS: (28, 100),
    SupplierCategory.INDUSTRIAL_EQUIPMENT: (35, 150),
    SupplierCategory.METALS: (20, 85),
    SupplierCategory.CHEMICALS: (18, 80),
    SupplierCategory.PACKAGING: (7, 45),
    SupplierCategory.LOGISTICS: (5, 35),
}

CRITICALITY_WEIGHTS: dict[Criticality, float] = {
    Criticality.LOW: 0.24,
    Criticality.MEDIUM: 0.42,
    Criticality.HIGH: 0.25,
    Criticality.CRITICAL: 0.09,
}

NAME_PREFIXES = (
    "Aster",
    "Bluepeak",
    "Cobalt",
    "Driftline",
    "Evercrest",
    "Ferrovia",
    "Granite",
    "Helio",
    "Ironvale",
    "Juniper",
    "Keystone",
    "Lumen",
    "Meridian",
    "Northline",
    "Orion",
    "Pinnacle",
    "Quartz",
    "Redwood",
    "Solstice",
    "Trident",
)
NAME_DESCRIPTORS = (
    "Atlas",
    "Axis",
    "Beacon",
    "Circuit",
    "Forge",
    "Harbor",
    "Matrix",
    "Nexus",
    "Summit",
    "Vector",
    "Vertex",
    "Vista",
)
NAME_SUFFIXES: dict[SupplierCategory, tuple[str, ...]] = {
    SupplierCategory.SEMICONDUCTORS: ("Silicon Works", "Wafer Systems", "Micro Devices"),
    SupplierCategory.ELECTRONIC_COMPONENTS: ("Component Labs", "Circuit Systems", "Signal Parts"),
    SupplierCategory.AUTOMOTIVE_COMPONENTS: (
        "Mobility Parts",
        "Drive Components",
        "Assembly Systems",
    ),
    SupplierCategory.INDUSTRIAL_EQUIPMENT: ("Machine Works", "Industrial Systems", "Tooling Group"),
    SupplierCategory.METALS: ("Alloy Materials", "Metalworks", "Foundry Supply"),
    SupplierCategory.CHEMICALS: ("Process Materials", "Chemical Supply", "Polymer Works"),
    SupplierCategory.PACKAGING: ("Packaging Systems", "Container Works", "Pack Materials"),
    SupplierCategory.LOGISTICS: ("Logistics Network", "Freight Systems", "Transit Group"),
}


def generate_suppliers(
    *, seed: int = SUPPLIER_GENERATOR_SEED, record_count: int = SUPPLIER_RECORD_COUNT
) -> tuple[Supplier, ...]:
    """Generate validated synthetic Supplier records deterministically."""

    if record_count != SUPPLIER_RECORD_COUNT:
        raise ValueError("Stage 7B generates exactly 120 Supplier records.")

    rng = random.Random(seed)
    categories = _planned_categories()
    criticalities = _planned_criticalities(rng)
    used_names: set[str] = set()

    suppliers: list[Supplier] = []
    for index in range(record_count):
        category = categories[index]
        criticality = criticalities[index]
        location = _choose_location(category, rng)
        supplier = Supplier(
            supplier_id=f"SUP-{index + 1:06d}",
            name=_supplier_name(category, rng, used_names),
            category=category,
            criticality=criticality,
            location=SupplierLocation(
                country_code=location.country_code,
                region=location.region,
                city=location.city,
                latitude=location.latitude,
                longitude=location.longitude,
            ),
            annual_spend_usd=_annual_spend(category, criticality, rng),
            typical_lead_time_days=_lead_time_days(category, rng),
            dependency_score=_dependency_score(criticality, rng),
            single_source=_single_source(criticality, rng),
        )
        suppliers.append(supplier)

    _validate_unique_names(suppliers)
    return tuple(suppliers)


def render_suppliers_jsonl(suppliers: tuple[Supplier, ...]) -> bytes:
    """Render Supplier records as deterministic UTF-8 JSONL bytes."""

    lines = [
        json.dumps(supplier.model_dump(mode="json"), sort_keys=True, separators=(",", ":"))
        for supplier in suppliers
    ]
    return ("\n".join(lines) + "\n").encode("utf-8")


def build_manifest(dataset_bytes: bytes) -> dict[str, object]:
    """Build deterministic manifest metadata for the Supplier dataset."""

    return {
        "dataset_name": SUPPLIER_DATASET_NAME,
        "generator_seed": SUPPLIER_GENERATOR_SEED,
        "generator_version": SUPPLIER_GENERATOR_VERSION,
        "record_count": SUPPLIER_RECORD_COUNT,
        "schema_path": SUPPLIER_SCHEMA_PATH.as_posix(),
        "sha256": hashlib.sha256(dataset_bytes).hexdigest(),
        "supplier_schema_version": SUPPLIER_SCHEMA_VERSION,
    }


def render_manifest_json(manifest: dict[str, object]) -> bytes:
    """Render manifest metadata as deterministic UTF-8 JSON bytes."""

    return (json.dumps(manifest, sort_keys=True, indent=2) + "\n").encode("utf-8")


def write_supplier_dataset(root: Path = Path(".")) -> None:
    """Write the canonical Supplier JSONL artifact and manifest."""

    suppliers = generate_suppliers()
    dataset_bytes = render_suppliers_jsonl(suppliers)
    manifest_bytes = render_manifest_json(build_manifest(dataset_bytes))

    dataset_path = root / SUPPLIER_DATASET_PATH
    manifest_path = root / SUPPLIER_MANIFEST_PATH
    dataset_path.parent.mkdir(parents=True, exist_ok=True)
    manifest_path.parent.mkdir(parents=True, exist_ok=True)
    dataset_path.write_bytes(dataset_bytes)
    manifest_path.write_bytes(manifest_bytes)


def _planned_categories() -> tuple[SupplierCategory, ...]:
    categories = tuple(SupplierCategory)
    return tuple(category for _ in range(15) for category in categories)


def _planned_criticalities(rng: random.Random) -> tuple[Criticality, ...]:
    values: list[Criticality] = []
    for criticality, weight in CRITICALITY_WEIGHTS.items():
        values.extend([criticality] * round(SUPPLIER_RECORD_COUNT * weight))
    while len(values) < SUPPLIER_RECORD_COUNT:
        values.append(Criticality.MEDIUM)
    values = values[:SUPPLIER_RECORD_COUNT]
    rng.shuffle(values)
    return tuple(values)


def _supplier_name(category: SupplierCategory, rng: random.Random, used_names: set[str]) -> str:
    candidates = [
        f"{prefix} {descriptor} {suffix}"
        for prefix in NAME_PREFIXES
        for descriptor in NAME_DESCRIPTORS
        for suffix in NAME_SUFFIXES[category]
    ]
    rng.shuffle(candidates)
    for candidate in candidates:
        if candidate not in used_names:
            used_names.add(candidate)
            return candidate
    raise ValueError(f"No unique synthetic supplier name available for {category.value}.")


def _choose_location(category: SupplierCategory, rng: random.Random) -> SyntheticLocation:
    countries = CATEGORY_LOCATION_COUNTRIES[category]
    eligible = tuple(
        location for location in LOCATION_CATALOG if location.country_code in countries
    )
    return rng.choice(eligible)


def _annual_spend(category: SupplierCategory, criticality: Criticality, rng: random.Random) -> int:
    low, high = SPEND_RANGES[category]
    multiplier = {
        Criticality.LOW: 0.65,
        Criticality.MEDIUM: 0.9,
        Criticality.HIGH: 1.15,
        Criticality.CRITICAL: 1.35,
    }[criticality]
    sampled = rng.randint(low, high)
    return max(1, round(sampled * multiplier / 1_000) * 1_000)


def _lead_time_days(category: SupplierCategory, rng: random.Random) -> int:
    low, high = LEAD_TIME_RANGES[category]
    return rng.randint(low, high)


def _dependency_score(criticality: Criticality, rng: random.Random) -> float:
    low, high = {
        Criticality.LOW: (0.08, 0.38),
        Criticality.MEDIUM: (0.22, 0.64),
        Criticality.HIGH: (0.45, 0.86),
        Criticality.CRITICAL: (0.62, 0.96),
    }[criticality]
    return round(rng.uniform(low, high), 2)


def _single_source(criticality: Criticality, rng: random.Random) -> bool:
    threshold = {
        Criticality.LOW: 0.04,
        Criticality.MEDIUM: 0.11,
        Criticality.HIGH: 0.25,
        Criticality.CRITICAL: 0.38,
    }[criticality]
    return rng.random() < threshold


def _validate_unique_names(suppliers: list[Supplier]) -> None:
    names = [supplier.name for supplier in suppliers]
    if len(names) != len(set(names)):
        raise ValueError("Generated supplier names must be unique.")
