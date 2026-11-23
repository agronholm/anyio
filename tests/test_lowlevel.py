from __future__ import annotations

import os
import signal
import sys
from contextvars import ContextVar
from threading import get_ident
from types import FrameType
from typing import Any

import pytest

from anyio import (
    Event,
    RunFinishedError,
    create_task_group,
    fail_after,
    get_available_backends,
    run,
    to_thread,
)
from anyio.lowlevel import (
    EventLoopToken,
    RunVar,
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


class TestTryRunSyncSoon:
    async def test_deferred(self) -> None:
        token = current_token()
        finished = Event()
        values: list[object] = []
        thread_id = get_ident()

        def callback(value: str, count: int) -> None:
            assert get_ident() == thread_id
            values.extend((value, count))
            finished.set()

        token.try_run_sync_soon(callback, "hello", 42)
        assert not values
        with fail_after(5):
            await finished.wait()

        assert values == ["hello", 42]

    async def test_context(self) -> None:
        marker: ContextVar[str] = ContextVar("marker", default="default")
        marker.set("caller")
        finished = Event()

        def callback() -> None:
            assert marker.get() == "caller"
            marker.set("callback")
            finished.set()

        current_token().try_run_sync_soon(callback)
        marker.set("changed")
        with fail_after(5):
            await finished.wait()

        assert marker.get() == "changed"

    async def test_from_thread(self) -> None:
        token = current_token()
        thread_id = get_ident()
        marker: ContextVar[str] = ContextVar("marker", default="default")
        finished = Event()

        def callback(value: str) -> None:
            assert get_ident() == thread_id
            assert current_token() == token
            assert marker.get() == "worker"
            assert value == "argument"
            finished.set()

        def worker() -> None:
            marker.set("worker")
            token.try_run_sync_soon(callback, "argument")

        with fail_after(5):
            await to_thread.run_sync(worker)
            await finished.wait()

        assert marker.get() == "default"

    @pytest.mark.parametrize("source_backend", get_available_backends())
    async def test_from_other_event_loop(self, source_backend: str) -> None:
        token = current_token()
        finished = Event()

        def callback() -> None:
            assert current_token() == token
            finished.set()

        async def source() -> None:
            token.try_run_sync_soon(callback)

        with fail_after(5):
            await to_thread.run_sync(lambda: run(source, backend=source_backend))
            await finished.wait()

    @pytest.mark.skipif(sys.platform == "win32", reason="Requires SIGUSR1")
    async def test_from_signal_handler(self) -> None:
        token = current_token()
        finished = Event()
        in_handler = False

        def callback() -> None:
            assert not in_handler
            assert current_token() == token
            finished.set()

        def handler(signum: int, frame: FrameType | None) -> None:
            nonlocal in_handler
            in_handler = True
            try:
                token.try_run_sync_soon(callback)
            finally:
                in_handler = False

        previous = signal.signal(signal.SIGUSR1, handler)
        try:
            os.kill(os.getpid(), signal.SIGUSR1)
            with fail_after(5):
                await finished.wait()
        finally:
            signal.signal(signal.SIGUSR1, previous)

    def test_finished_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def get_token() -> EventLoopToken:
            return current_token()

        token = run(
            get_token, backend=anyio_backend_name, backend_options=anyio_backend_options
        )
        with pytest.raises(RunFinishedError):
            token.try_run_sync_soon(lambda: None)


@pytest.mark.skipif(
    "trio" not in get_available_backends(), reason="Trio is unavailable"
)
def test_run_sync_soon_runs_callback_before_exit() -> None:
    values: list[str] = []

    async def main() -> EventLoopToken:
        token = current_token()
        token.run_sync_soon(values.append, "callback")
        assert not values
        return token

    token = run(main, backend="trio")
    assert values == ["callback"]
    with pytest.raises(RunFinishedError):
        token.run_sync_soon(values.append, "after exit")


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_run_sync_soon_unsupported() -> None:
    with pytest.raises(NotImplementedError, match="guaranteed callback scheduling"):
        current_token().run_sync_soon(pytest.fail, "Callback should not be scheduled")
