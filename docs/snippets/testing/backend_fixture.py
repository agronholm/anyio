import sys
from typing import Any

import pytest


@pytest.fixture(
    params=[
        pytest.param(("asyncio", {"use_uvloop": True}), id="asyncio+uvloop"),
        pytest.param(("asyncio", {"use_uvloop": False}), id="asyncio"),
        pytest.param(
            ("trio", {"restrict_keyboard_interrupt_to_checkpoints": True}), id="trio"
        ),
    ]
)
def anyio_backend(request: pytest.FixtureRequest) -> tuple[str, dict[str, Any]]:
    backend, options = request.param
    if backend == "asyncio" and options.get("use_uvloop"):
        pytest.importorskip("winloop" if sys.platform == "win32" else "uvloop")

    return request.param
