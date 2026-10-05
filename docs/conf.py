from __future__ import annotations

import subprocess
import sys
from importlib.metadata import version as get_version
from pathlib import Path

from packaging.version import parse
from sphinx.application import Sphinx

extensions = [
    "sphinx.ext.autodoc",
    "sphinx.ext.intersphinx",
    "sphinx_tabs.tabs",
    "sphinx_autodoc_typehints",
    "sphinx_rtd_theme",
]

templates_path = ["_templates"]
source_suffix = ".rst"
master_doc = "index"
project = "AnyIO"
author = "Alex Grönholm"
copyright = "2018, " + author

v = parse(get_version("anyio"))
version = v.base_version
release = v.public

language = "en"

exclude_patterns = ["_build"]
pygments_style = "sphinx"
autodoc_default_options = {"members": True, "show-inheritance": True}
autodoc_mock_imports = ["_typeshed", "pytest", "_pytest"]
todo_include_todos = False
suppress_warnings = ["config.cache"]


def fixup_module_name(module: str) -> str:
    if module.startswith("anyio.abc._"):
        return "anyio.abc"
    elif module.startswith("anyio._"):
        return "anyio"
    else:
        return module


typehints_fixup_module_name = fixup_module_name
html_theme = "sphinx_rtd_theme"
htmlhelp_basename = "anyiodoc"

intersphinx_mapping = {"python": ("https://docs.python.org/3/", None)}

project_root = Path(__file__).parent.parent
towncrier_marker = ".. towncrier release notes start\n"


def insert_unreleased_changes(app: Sphinx, docname: str, source: list[str]) -> None:
    # Render the pending news fragments into the version history as a draft
    if docname == "versionhistory" and any(
        path.name != "template.rst.j2"
        for path in project_root.joinpath("changelog.d").iterdir()
    ):
        draft = subprocess.run(
            [sys.executable, "-m", "towncrier", "build", "--draft"]
            + ["--version", "UNRELEASED"],
            cwd=project_root,
            capture_output=True,
            text=True,
            check=True,
        ).stdout
        source[0] = source[0].replace(towncrier_marker, f"{draft}\n")


def setup(app: Sphinx) -> None:
    app.connect("source-read", insert_unreleased_changes)
