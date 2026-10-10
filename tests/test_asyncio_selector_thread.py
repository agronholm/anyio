from __future__ import annotations

import asyncio
import socket
from collections.abc import Iterator
from contextlib import suppress
from selectors import EVENT_READ, EVENT_WRITE
from typing import Any

import pytest
from _pytest.monkeypatch import MonkeyPatch

from anyio import wait_all_tasks_blocked, wait_readable, wait_writable
from anyio._core._asyncio_selector_thread import Selector


@pytest.fixture
def anyio_backend() -> str:
    return "asyncio"


@pytest.fixture
def selector(deactivate_blockbuster: None) -> Iterator[Selector]:
    selector = Selector()
    try:
        yield selector
    finally:
        selector._send.close()
        selector._receive.close()
        selector._selector.close()


@pytest.mark.parametrize("event", [EVENT_READ, EVENT_WRITE])
async def test_remove_missing_interest(selector: Selector, event: int) -> None:
    sock, peer = socket.socketpair()
    with sock, peer:
        add_other = selector.add_writer if event == EVENT_READ else selector.add_reader
        remove = (
            selector.remove_reader if event == EVENT_READ else selector.remove_writer
        )
        remove_other = (
            selector.remove_writer if event == EVENT_READ else selector.remove_reader
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
async def test_remove_existing_interest(selector: Selector, event: int) -> None:
    sock, peer = socket.socketpair()
    with sock, peer:
        selector.add_reader(sock, lambda: None)
        selector.add_writer(sock, lambda: None)
        remove = (
            selector.remove_reader if event == EVENT_READ else selector.remove_writer
        )
        remove_other = (
            selector.remove_writer if event == EVENT_READ else selector.remove_reader
        )
        assert remove(sock) is True
        assert remove_other(sock) is True
        assert remove(sock) is False


@pytest.mark.parametrize("event", [EVENT_READ, EVENT_WRITE])
async def test_wait_callback_with_opposite_interest(
    selector: Selector, event: int, monkeypatch: MonkeyPatch
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
        add_other = selector.add_writer if event == EVENT_READ else selector.add_reader
        remove = (
            selector.remove_reader if event == EVENT_READ else selector.remove_writer
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
