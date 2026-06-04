from __future__ import annotations

import asyncio
from typing import Any

import pytest

from anyio import create_task_group, run
from anyio._backends import _asyncio
from anyio._backends._asyncio import AsyncIOBackend, CancelScope
from anyio.lowlevel import (
    RunVar,
    cancel_shielded_checkpoint,
    checkpoint,
    checkpoint_if_cancelled,
)


@pytest.mark.parametrize("cancel", [False, True])
async def test_checkpoint_if_cancelled(cancel: bool) -> None:
    finished = second_finished = False

    async def func() -> None:
        nonlocal finished
        tg.start_soon(second_func)
        if cancel:
            tg.cancel_scope.cancel()

        await checkpoint_if_cancelled()
        finished = True

    async def second_func() -> None:
        nonlocal second_finished
        assert finished != cancel
        second_finished = True

    async with create_task_group() as tg:
        tg.start_soon(func)

    assert finished != cancel
    assert second_finished


@pytest.mark.parametrize("cancel", [False, True])
async def test_cancel_shielded_checkpoint(cancel: bool) -> None:
    finished = second_finished = False

    async def func() -> None:
        nonlocal finished
        await cancel_shielded_checkpoint()
        finished = True

    async def second_func() -> None:
        nonlocal second_finished
        assert not finished
        second_finished = True

    async with create_task_group() as tg:
        tg.start_soon(func)
        tg.start_soon(second_func)
        if cancel:
            tg.cancel_scope.cancel()

    assert finished
    assert second_finished


@pytest.mark.parametrize("cancel", [False, True])
async def test_checkpoint(cancel: bool) -> None:
    finished = second_finished = False

    async def func() -> None:
        nonlocal finished
        await checkpoint()
        finished = True

    async def second_func() -> None:
        nonlocal second_finished
        assert not finished
        second_finished = True

    async with create_task_group() as tg:
        tg.start_soon(func)
        tg.start_soon(second_func)
        if cancel:
            tg.cancel_scope.cancel()

    assert finished != cancel
    assert second_finished


def test_cancel_scope_without_running_task(
    asyncio_event_loop: asyncio.AbstractEventLoop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Entering a cancel scope without a current task raises a clear error (asyncio).

    Regression test: previously this raised an obscure
    ``TypeError: cannot create weak reference to 'NoneType' object`` because
    ``current_task()`` returned ``None`` and that ``None`` was then used as a key in
    a ``WeakKeyDictionary``.
    """
    monkeypatch.setattr(_asyncio, "current_task", lambda: None)

    async def main() -> None:
        with pytest.raises(
            RuntimeError, match="A cancel scope can only be entered from within a task"
        ):
            with CancelScope():
                pass

    asyncio_event_loop.run_until_complete(main())


def test_cancel_shielded_checkpoint_without_task(
    asyncio_event_loop: asyncio.AbstractEventLoop,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """cancel_shielded_checkpoint() must not crash without a current task (asyncio).

    Library primitives such as ``CapacityLimiter`` reach this code path while
    ``current_task()`` may return ``None``; it must degrade to a plain checkpoint
    instead of raising ``TypeError``.
    """
    monkeypatch.setattr(_asyncio, "current_task", lambda: None)
    asyncio_event_loop.run_until_complete(AsyncIOBackend.cancel_shielded_checkpoint())


class TestRunVar:
    def test_get_set(
        self,
        anyio_backend_name: str,
        anyio_backend_options: dict[str, Any],
    ) -> None:
        async def taskfunc(index: int) -> None:
            assert var.get() == index
            var.set(index + 1)

        async def main() -> None:
            pytest.raises(LookupError, var.get)
            for i in range(2):
                var.set(i)
                async with create_task_group() as tg:
                    tg.start_soon(taskfunc, i)

                assert var.get() == i + 1

        var = RunVar[int]("var")
        for _ in range(2):
            run(main, backend=anyio_backend_name, backend_options=anyio_backend_options)

    async def test_reset_token_used_on_wrong_runvar(self) -> None:
        var1 = RunVar[str]("var1")
        var2 = RunVar[str]("var2")
        token = var1.set("blah")
        with pytest.raises(
            ValueError, match="This token does not belong to this RunVar"
        ):
            var2.reset(token)

    async def test_reset_token_used_twice(self) -> None:
        var = RunVar[str]("var")
        token = var.set("blah")
        var.reset(token)
        with pytest.raises(ValueError, match="This token has already been used"):
            var.reset(token)

    async def test_runvar_does_not_share_storage_by_name(self) -> None:
        var1: RunVar[int] = RunVar("var", 1)
        var2: RunVar[str] = RunVar("var", "a")

        assert var1.get() == 1
        assert var2.get() == "a"

        var1.set(2)
        var2.set("b")

        assert var1.get() == 2
        assert var2.get() == "b"

    async def test_context_manager(self) -> None:
        var = RunVar[int]("var", default=3)
        with var.set(4):
            with var.set(5):
                assert var.get() == 5

            assert var.get() == 4

        assert var.get() == 3
