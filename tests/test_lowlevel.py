from __future__ import annotations

import gc
import weakref
from typing import Any

import pytest

from anyio import create_task_group, run
from anyio.from_thread import start_blocking_portal
from anyio.lowlevel import (
    RunVar,
    RunvarToken,
    cancel_shielded_checkpoint,
    checkpoint,
    checkpoint_if_cancelled,
    current_token,
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

    def test_reset_token_from_finished_event_loop(
        self,
        anyio_backend_name: str,
        anyio_backend_options: dict[str, Any],
    ) -> None:
        var = RunVar[str]("var", default="default")

        async def first_loop() -> tuple[RunvarToken[str], RunvarToken[str]]:
            token_unset = var.set("first")
            token_prev = var.set("second")
            return token_unset, token_prev

        async def second_loop() -> None:
            var.set("loop2")
            with pytest.raises(
                ValueError, match="This token was created in a different event loop"
            ):
                var.reset(token_unset)

            assert var.get() == "loop2"

            with pytest.raises(
                ValueError, match="This token was created in a different event loop"
            ):
                var.reset(token_prev)

            assert var.get() == "loop2"

        token_unset, token_prev = run(
            first_loop,
            backend=anyio_backend_name,
            backend_options=anyio_backend_options,
        )
        run(
            second_loop,
            backend=anyio_backend_name,
            backend_options=anyio_backend_options,
        )

    def test_reset_token_from_concurrent_event_loop(
        self,
        anyio_backend_name: str,
        anyio_backend_options: dict[str, Any],
    ) -> None:
        var = RunVar[str]("var", default="default")

        with start_blocking_portal(
            backend=anyio_backend_name, backend_options=anyio_backend_options
        ) as portal:
            token = portal.call(var.set, "loop1")
            assert portal.call(var.get) == "loop1"

            async def other_loop() -> None:
                var.set("loop2")
                with pytest.raises(
                    ValueError, match="This token was created in a different event loop"
                ):
                    var.reset(token)

                assert var.get() == "loop2"

            run(
                other_loop,
                backend=anyio_backend_name,
                backend_options=anyio_backend_options,
            )

            # The rejected cross-loop reset must not redeem the token
            portal.call(var.reset, token)
            assert portal.call(var.get) == "default"

    def test_token_does_not_keep_finished_loop_alive(
        self,
        anyio_backend_name: str,
        anyio_backend_options: dict[str, Any],
    ) -> None:
        var = RunVar[str]("var")

        async def main() -> tuple[RunvarToken[str], weakref.ref[object]]:
            token = var.set("value")
            return token, weakref.ref(current_token().native_token)

        token, loop_ref = run(
            main, backend=anyio_backend_name, backend_options=anyio_backend_options
        )
        gc.collect()
        gc.collect()
        assert loop_ref() is None
        assert token is not None
