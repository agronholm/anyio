from __future__ import annotations

import sys
from collections.abc import AsyncGenerator
from functools import partial

import pytest
from pytest import fixture

from anyio import to_interpreter

requires_py314 = pytest.mark.skipif(
    sys.version_info < (3, 14), reason="requires Python 3.14+"
)


@fixture(autouse=True)
async def destroy_workers() -> AsyncGenerator[None]:
    yield
    idle_workers = to_interpreter._idle_workers.get()
    for worker in idle_workers:
        worker.destroy()

    idle_workers.clear()


@pytest.mark.skipif(sys.version_info >= (3, 14), reason="requires Python < 3.14")
async def test_run_sync_requires_python_314() -> None:
    with pytest.raises(
        RuntimeError, match="subinterpreters require at least Python 3.14"
    ):
        await to_interpreter.run_sync(int, "1")


@requires_py314
async def test_run_sync() -> None:
    """
    Test that the function runs in a different interpreter, and the same interpreter in
    both calls.

    """
    from concurrent.interpreters import get_current

    main_interpreter_id = get_current().id
    interpreter_id = (await to_interpreter.run_sync(get_current)).id
    interpreter_id_2 = (await to_interpreter.run_sync(get_current)).id
    assert interpreter_id == interpreter_id_2
    assert interpreter_id != main_interpreter_id


@requires_py314
async def test_args_kwargs() -> None:
    """Test that partial() can be used to pass keyword arguments."""
    result = await to_interpreter.run_sync(partial(sorted, reverse=True), ["a", "b"])
    assert result == ["b", "a"]


@requires_py314
async def test_exception() -> None:
    """Test that exceptions are delivered properly."""
    with pytest.raises(ValueError, match="invalid literal for int"):
        assert await to_interpreter.run_sync(int, "a")
