"""Project-owned warehouse exception boundary."""

from __future__ import annotations


class WarehouseError(Exception):
    """Base class for warehouse boundary failures."""


class WarehouseConfigurationError(WarehouseError):
    """Raised when warehouse configuration is invalid."""


class WarehouseWriteError(WarehouseError):
    """Raised when a warehouse load job fails."""


class WarehouseJobTimeoutError(WarehouseWriteError):
    """Raised when a warehouse load job does not finish in time."""
