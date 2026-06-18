from __future__ import annotations

__all__ = ("install_lazy_importer",)

import ast
import inspect
import sys
import warnings
from importlib import import_module
from types import ModuleType
from typing import Any


def install_lazy_importer() -> bool:
    module_globals = sys._getframe(1).f_globals
    module_name = module_globals["__name__"]
    module_prefix = module_name + "."
    module = sys.modules[module_name]
    lazy_map, deprecated_aliases = _build_lazy_map(module)
    if not lazy_map:
        return False

    def __getattr__(name: str) -> Any:
        if new_name := deprecated_aliases.get(name):
            warnings.warn(
                f"The {name!r} alias is deprecated, use {new_name!r} instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            name = new_name

        try:
            target_mod, target_attr = lazy_map[name]
        except KeyError:
            raise AttributeError(
                f"module {module_name!r} has no attribute {name!r}"
            ) from None

        imported = import_module(target_mod, module_name)
        value = getattr(imported, target_attr)

        # patch the module name to match
        if getattr(value, "__module__", "").startswith(module_prefix):
            value.__module__ = module_name

        module.__dict__[name] = value
        return value

    module.__dict__["__getattr__"] = __getattr__
    module.__dict__["__all__"] = list(lazy_map)
    return True


def _build_lazy_map(
    module: ModuleType,
) -> tuple[dict[str, tuple[str, str]], dict[str, str]]:
    try:
        source = inspect.getsource(module)
    except OSError:
        return {}, {}

    tree = compile(source, module.__file__ or "", "exec", ast.PyCF_ONLY_AST)
    assert isinstance(tree, ast.Module)
    out: dict[str, tuple[str, str]] = {}
    deprecated_aliases: dict[str, str] = {}

    for node in tree.body:
        if not isinstance(node, ast.If) or not _is_type_checking_block(node.test):
            continue

        for stmt in node.body:
            match stmt:
                case ast.ImportFrom():
                    base = "." * stmt.level + (stmt.module or "")
                    for alias in stmt.names:
                        if alias.name == "*":
                            raise RuntimeError("star imports not supported")

                        exported = alias.asname or alias.name
                        out[exported] = (base, alias.name)
                case ast.Assign():
                    if isinstance(stmt.value, ast.Name):
                        new_name = stmt.value.id
                        for target in stmt.targets:
                            if isinstance(target, ast.Name):
                                deprecated_aliases[target.id] = new_name

    return out, deprecated_aliases


def _is_type_checking_block(test: ast.AST) -> bool:
    match test:
        case ast.Name():
            return test.id == "TYPE_CHECKING"
        case ast.Attribute():
            return (
                isinstance(test.value, ast.Name)
                and test.value.id == "typing"
                and test.attr == "TYPE_CHECKING"
            )
        case _:
            return False
