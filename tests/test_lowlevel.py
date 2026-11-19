from __future__ import annotations

import asyncio
from typing import Any

import pytest
from pytest import MonkeyPatch

from anyio import CancelScope, create_task_group, run
from anyio.lowlevel import (
    RunVar,
    cancel_shielded_checkpoint,
    checkpoint,
    checkpoint_if_cancelled,
)

from .conftest import asyncio_params


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


@pytest.mark.parametrize("anyio_backend", asyncio_params)
async def test_cancel_shielded_checkpoint_delivered_cancellation() -> None:
    task = asyncio.current_task()
    assert task is not None

    with CancelScope() as scope:
        scope.cancel()
        for _ in range(3):
            await cancel_shielded_checkpoint()

            # The scope's cancellation is delivered inside the checkpoint, which
            # swallows it and returns instead of letting it propagate
            assert task.cancelling() > 0

    # Exiting the scope undoes the cancellation requests it made on the task
    assert task.cancelling() == 0


@pytest.mark.parametrize("anyio_backend", asyncio_params)
async def test_cancel_shielded_checkpoint_propagates_external_cancel() -> None:
    task = asyncio.current_task()
    assert task is not None
    task.cancel()

    with pytest.raises(asyncio.CancelledError):
        await cancel_shielded_checkpoint()


@pytest.mark.parametrize("anyio_backend", asyncio_params)
async def test_cancel_shielded_checkpoint_enters_no_scope(
    monkeypatch: MonkeyPatch,
) -> None:
    scope_entries = 0
    scope_type = type(CancelScope())
    original_enter = scope_type.__enter__

    def counting_enter(self: Any) -> Any:
        nonlocal scope_entries
        scope_entries += 1
        return original_enter(self)

    monkeypatch.setattr(scope_type, "__enter__", counting_enter)
    await cancel_shielded_checkpoint()

    assert scope_entries == 0


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
