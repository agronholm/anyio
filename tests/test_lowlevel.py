from __future__ import annotations

from typing import Any

import pytest

from anyio import create_task_group, run
from anyio.lowlevel import (
    RunVar,
    cancel_shielded_checkpoint,
    checkpoint,
    checkpoint_if_cancelled,
)

pytestmark = pytest.mark.anyio


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
