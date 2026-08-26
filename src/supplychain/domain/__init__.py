"""Public domain contracts for SupplyChain Sentinel."""

from supplychain.domain.suppliers import (
    SUPPLIER_SCHEMA_VERSION,
    Criticality,
    Supplier,
    SupplierCategory,
    SupplierLocation,
)

__all__ = [
    "SUPPLIER_SCHEMA_VERSION",
    "Criticality",
    "Supplier",
    "SupplierCategory",
    "SupplierLocation",
]
