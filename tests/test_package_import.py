from importlib import import_module
from types import ModuleType


def test_package_imports() -> None:
    module = import_module("supplychain")

    assert isinstance(module, ModuleType)
    assert module.__name__ == "supplychain"
