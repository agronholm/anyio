from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from contextlib import suppress
from selectors import EVENT_READ, EVENT_WRITE
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from anyio import (
    create_task_group,
    run,
    wait_all_tasks_blocked,
    wait_readable,
    wait_writable,
)
from anyio._core._asyncio_selector_thread import Selector
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


class TestAsyncioSelector:
    @pytest.fixture
    def anyio_backend(self) -> str:
        return "asyncio"

    @pytest.fixture
    def selector(self, deactivate_blockbuster: None) -> Iterator[Selector]:
        selector = Selector()
        try:
            yield selector
        finally:
            selector._send.close()
            selector._receive.close()
            selector._selector.close()

    @pytest.mark.parametrize("event", [EVENT_READ, EVENT_WRITE])
    async def test_remove_missing_interest(
        self, selector: Selector, event: int
    ) -> None:
        sock, peer = socket.socketpair()
        with sock, peer:
            add_other = (
                selector.add_writer if event == EVENT_READ else selector.add_reader
            )
            remove = (
                selector.remove_reader
                if event == EVENT_READ
                else selector.remove_writer
            )
            remove_other = (
                selector.remove_writer
                if event == EVENT_READ
                else selector.remove_reader
            )

            def callback() -> None:
                pass

            add_other(sock, callback)
            before = selector._selector.get_key(sock)
            assert remove(sock) is False
            assert remove(sock) is False
            assert selector._selector.get_key(sock) == before
            assert remove_other(sock) is True
            assert remove_other(sock) is False

    @pytest.mark.parametrize("event", [EVENT_READ, EVENT_WRITE])
    async def test_remove_existing_interest(
        self, selector: Selector, event: int
    ) -> None:
        sock, peer = socket.socketpair()
        with sock, peer:
            selector.add_reader(sock, lambda: None)
            selector.add_writer(sock, lambda: None)
            remove = (
                selector.remove_reader
                if event == EVENT_READ
                else selector.remove_writer
            )
            remove_other = (
                selector.remove_writer
                if event == EVENT_READ
                else selector.remove_reader
            )
            assert remove(sock) is True
            assert remove_other(sock) is True
            assert remove(sock) is False

    @pytest.mark.parametrize("event", [EVENT_READ, EVENT_WRITE])
    async def test_wait_callback_with_opposite_interest(
        self, selector: Selector, event: int, monkeypatch: MonkeyPatch
    ) -> None:
        def unsupported(*args: Any, **kwargs: Any) -> None:
            raise NotImplementedError

        loop = asyncio.get_running_loop()
        for method in ("add_reader", "add_writer", "remove_reader", "remove_writer"):
            monkeypatch.setattr(loop, method, unsupported)

        monkeypatch.setattr(
            "anyio._core._asyncio_selector_thread.get_selector", lambda: selector
        )
        sock, peer = socket.socketpair()
        with sock, peer:
            wait = wait_readable if event == EVENT_READ else wait_writable
            add_other = (
                selector.add_writer if event == EVENT_READ else selector.add_reader
            )
            remove = (
                selector.remove_reader
                if event == EVENT_READ
                else selector.remove_writer
            )
            other_event = EVENT_WRITE if event == EVENT_READ else EVENT_READ
            add_other(sock, lambda: None)
            task = asyncio.ensure_future(wait(sock))
            try:
                await wait_all_tasks_blocked()
                key = selector._selector.get_key(sock)
                callback = key.data[event][1]
                assert remove(sock)
                callback()
                await task
                assert selector._selector.get_key(sock).events == other_event
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
