from __future__ import annotations

import sys

import pytest

from anyio import to_interpreter

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(sys.version_info < (3, 13), reason="requires Python 3.13+"),
]


async def test_run_sync() -> None:
    """
    Test that the function runs in a different interpreter, and the same interpreter in
    both calls.

    """
    import _interpreters

    main_interpreter_id, _ = _interpreters.get_current()
    interpreter_id, _ = await to_interpreter.run_sync(_interpreters.get_current)
    interpreter_id_2, _ = await to_interpreter.run_sync(_interpreters.get_current)
    assert interpreter_id == interpreter_id_2
    assert interpreter_id != main_interpreter_id


async def test_args_kwargs() -> None:
    """Test that partial() can be used to pass keyword arguments."""
    result = await to_interpreter.run_sync(sorted, ["a", "b"], kwargs={"reverse": True})
    assert result == ["b", "a"]


async def test_exception() -> None:
    """Test that exceptions are delivered properly."""
    with pytest.raises(ValueError, match="invalid literal for int"):
        assert await to_interpreter.run_sync(int, "a")
