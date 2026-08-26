from __future__ import annotations

import hashlib
import json
from collections import Counter
from pathlib import Path
from typing import cast

from supplychain.domain import SUPPLIER_SCHEMA_VERSION, Criticality, Supplier, SupplierCategory
from supplychain.domain.synthetic_suppliers import (
    SUPPLIER_DATASET_NAME,
    SUPPLIER_DATASET_PATH,
    SUPPLIER_GENERATOR_SEED,
    SUPPLIER_GENERATOR_VERSION,
    SUPPLIER_MANIFEST_PATH,
    SUPPLIER_RECORD_COUNT,
    SUPPLIER_SCHEMA_PATH,
    generate_suppliers,
    render_suppliers_jsonl,
)


def dataset_bytes() -> bytes:
    return SUPPLIER_DATASET_PATH.read_bytes()


def manifest() -> dict[str, object]:
    return cast(dict[str, object], json.loads(SUPPLIER_MANIFEST_PATH.read_text(encoding="utf-8")))


def dataset_records() -> list[dict[str, object]]:
    return [
        json.loads(line)
        for line in SUPPLIER_DATASET_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]


def validated_suppliers() -> list[Supplier]:
    return [
        Supplier.model_validate_json(line)
        for line in SUPPLIER_DATASET_PATH.read_text(encoding="utf-8").splitlines()
        if line
    ]


def test_manifest_integrity_metadata() -> None:
    metadata = manifest()

    assert metadata == {
        "dataset_name": SUPPLIER_DATASET_NAME,
        "generator_seed": SUPPLIER_GENERATOR_SEED,
        "generator_version": SUPPLIER_GENERATOR_VERSION,
        "record_count": SUPPLIER_RECORD_COUNT,
        "schema_path": SUPPLIER_SCHEMA_PATH.as_posix(),
        "sha256": hashlib.sha256(dataset_bytes()).hexdigest(),
        "supplier_schema_version": SUPPLIER_SCHEMA_VERSION,
    }
    assert Path(str(metadata["schema_path"])).is_file()


def test_dataset_has_exactly_120_valid_supplier_records() -> None:
    suppliers = validated_suppliers()

    assert len(suppliers) == SUPPLIER_RECORD_COUNT
    assert all(supplier.schema_version == SUPPLIER_SCHEMA_VERSION for supplier in suppliers)


def test_supplier_ids_are_unique_and_sequential() -> None:
    supplier_ids = [supplier.supplier_id for supplier in validated_suppliers()]
    expected_ids = [f"SUP-{index:06d}" for index in range(1, SUPPLIER_RECORD_COUNT + 1)]

    assert supplier_ids == expected_ids
    assert len(supplier_ids) == len(set(supplier_ids))


def test_supplier_names_are_unique() -> None:
    names = [supplier.name for supplier in validated_suppliers()]

    assert len(names) == len(set(names))


def test_all_categories_and_criticality_values_appear() -> None:
    suppliers = validated_suppliers()

    assert {supplier.category for supplier in suppliers} == set(SupplierCategory)
    assert {supplier.criticality for supplier in suppliers} == set(Criticality)


def test_dataset_has_geographic_diversity() -> None:
    country_codes = {supplier.location.country_code for supplier in validated_suppliers()}

    assert len(country_codes) >= 10


def test_single_source_states_appear_and_true_is_minority() -> None:
    counts = Counter(supplier.single_source for supplier in validated_suppliers())

    assert counts[True] > 0
    assert counts[False] > 0
    assert counts[True] < counts[False]


def test_dependency_scores_show_meaningful_variation() -> None:
    scores = [supplier.dependency_score for supplier in validated_suppliers()]

    assert len(set(scores)) >= 20
    assert max(scores) - min(scores) >= 0.5


def test_annual_spend_values_show_meaningful_variation() -> None:
    spend_values = [supplier.annual_spend_usd for supplier in validated_suppliers()]

    assert len(set(spend_values)) >= 40
    assert max(spend_values) > min(spend_values) * 10


def test_location_coordinates_remain_valid() -> None:
    for supplier in validated_suppliers():
        assert -90.0 <= supplier.location.latitude <= 90.0
        assert -180.0 <= supplier.location.longitude <= 180.0


def test_canonical_dataset_regenerates_byte_for_byte() -> None:
    regenerated = render_suppliers_jsonl(generate_suppliers())

    assert regenerated == dataset_bytes()


def test_manifest_checksum_matches_dataset_bytes() -> None:
    assert manifest()["sha256"] == hashlib.sha256(dataset_bytes()).hexdigest()


def test_generated_artifact_has_no_duplicate_full_records() -> None:
    lines = SUPPLIER_DATASET_PATH.read_text(encoding="utf-8").splitlines()

    assert len(lines) == SUPPLIER_RECORD_COUNT
    assert len(lines) == len(set(lines))
