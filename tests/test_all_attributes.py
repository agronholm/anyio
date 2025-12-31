from __future__ import annotations

import pkgutil
from importlib import import_module
from inspect import isclass
from types import FunctionType

import pytest

import anyio


def test_all_attributes() -> None:
    """
    Check that all exported functions and classes of all public modules are present in
    the __all__ attribute of the module.

    """
    for _finder, name, ispkg in pkgutil.walk_packages(anyio.__path__, "anyio."):
        if ispkg or "._" in name or name == "anyio.pytest_plugin":
            continue

        module = import_module(name)
        all_names = getattr(module, "__all__", None)
        if all_names is None:
            pytest.fail(f"Module {module.__name__} has no __all__ attribute")

        if not isinstance(all_names, tuple):
            pytest.fail(f"{module.__name__}.__all__ is not a tuple")

        exported_names = set[str]()
        for attr in dir(module):
            if attr.startswith("_"):
                continue

            value = getattr(module, attr)
            if isinstance(value, FunctionType) or isclass(value):
                if value.__module__ == module.__name__:
                    exported_names.add(attr)

        if missing := exported_names - set(all_names):
            pytest.fail(
                f"The following names are exported by {module.__name__} but not in its "
                f"__all__ attribute: {', '.join(sorted(missing))}"
            )

        if extra := set(all_names) - exported_names:
            pytest.fail(
                f"The following names are present in {module.__name__}.__all__ but are "
                f"not exported by the module: {', '.join(sorted(extra))}"
            )
