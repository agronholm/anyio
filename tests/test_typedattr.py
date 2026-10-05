from __future__ import annotations

import subprocess
import sys
from collections.abc import Callable, Mapping
from pathlib import Path
from typing import Any

import pytest

from anyio import TypedAttributeProvider


class DummyAttributeProvider(TypedAttributeProvider):
    def get_dummyattr(self) -> str:
        raise KeyError("foo")

    @property
    def extra_attributes(self) -> Mapping[Any, Callable[[], Any]]:
        return {str: self.get_dummyattr}


def test_sentinel_import_on_python_315_alpha() -> None:
    """
    Python 3.15.0a5 compares as 3.15 but has no ``sentinel`` builtin.

    The import block in each caller must still bind ``sentinel`` there.

    """
    root = Path(__file__).parents[1]
    sources = [
        root / "src/anyio/_core/_typedattr.py",
        root / "src/anyio/itertools.py",
        root / "src/anyio/_backends/_trio.py",
    ]
    script = """\
import ast
import sys
import types
from pathlib import Path

# Pretend this is 3.15.0a5. A stand-in typing_extensions avoids importing the
# real one, which reads sys.version_info during its own import.
sys.version_info = (3, 15, 0, "alpha", 5)
typing_extensions = types.ModuleType("typing_extensions")
typing_extensions.sentinel = lambda name: object()
sys.modules["typing_extensions"] = typing_extensions

for name in sys.argv[1:]:
    source = Path(name).read_text()
    block = None
    for node in ast.parse(source).body:
        if isinstance(node, ast.If):
            segment = ast.get_source_segment(source, node)
            if segment and "import sentinel" in segment:
                block = segment
                break
    if block is None:
        raise SystemExit(f"no sentinel import in {name}")
    namespace = {"sys": sys}
    exec(block, namespace)
    namespace["sentinel"]("undefined")
"""
    result = subprocess.run(
        [sys.executable, "-c", script, *(str(path) for path in sources)],
        check=False,
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr


def test_typedattr_keyerror() -> None:
    """
    Test that if the extra attribute getter raises KeyError, it won't be confused for a
    missing attribute.

    """
    with pytest.raises(KeyError, match="^'foo'$"):
        DummyAttributeProvider().extra(str)
