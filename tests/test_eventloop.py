from __future__ import annotations

import asyncio
import gc
import math
import sys
import time
import weakref
from asyncio import get_running_loop
from collections.abc import Generator
from typing import Any
from unittest import mock
from unittest.mock import AsyncMock

import pytest
from pytest import MonkeyPatch

from anyio import current_time, run, sleep, sleep_forever, sleep_until, to_thread

from .conftest import return_non_coro_awaitable

fake_current_time = 1620581544.0


@pytest.fixture
def fake_sleep() -> Generator[AsyncMock, None, None]:
    with mock.patch(
        "anyio._core._eventloop.current_time", return_value=fake_current_time
    ):
        with mock.patch("anyio._core._eventloop.sleep", AsyncMock()) as v:
            yield v


async def test_sleep_until(fake_sleep: AsyncMock) -> None:
    deadline = fake_current_time + 500.102352
    await sleep_until(deadline)
    fake_sleep.assert_called_once_with(deadline - fake_current_time)


async def test_sleep_until_in_past(fake_sleep: AsyncMock) -> None:
    deadline = fake_current_time - 500.102352
    await sleep_until(deadline)
    fake_sleep.assert_called_once_with(0)


async def test_sleep_forever(fake_sleep: AsyncMock) -> None:
    await sleep_forever()
    fake_sleep.assert_called_once_with(math.inf)


def test_run_task() -> None:
    """Test that anyio.run() on asyncio will work with a callable returning a Future."""

    async def async_add(x: int, y: int) -> int:
        return x + y

    result = run(asyncio.create_task, async_add(1, 2), backend="asyncio")
    assert result == 3


def test_run_non_corofunc(
    anyio_backend_name: str, anyio_backend_options: dict[str, Any]
) -> None:
    @return_non_coro_awaitable
    async def async_add(x: int, y: int) -> int:
        return x + y

    result = run(
        async_add,
        1,
        2,
        backend=anyio_backend_name,
        backend_options=anyio_backend_options,
    )
    assert result == 3


def test_run_unknown_backend() -> None:
    async def main() -> None:
        pass

    with pytest.raises(LookupError, match="No such backend: somebackend"):
        run(main, backend="somebackend")


@pytest.mark.skipif(
    sys.implementation.name != "cpython",
    reason="garbage collection semantics differ on non-CPython implementations",
)
def test_asyncio_run_does_not_leak_event_loop() -> None:
    """
    Regression test for #1203.

    ``find_root_task()`` caches the root task in a per-loop run-var. Because the
    cached task strong-references its event loop (the weak *key* of the run-vars
    mapping), the loop -- and the run's result -- could never be garbage-collected,
    leaking on every ``anyio.run()`` that used ``to_thread.run_sync()``.
    """

    def thread_worker() -> None:
        pass

    loop_refs: list[weakref.ref[asyncio.AbstractEventLoop]] = []

    async def main() -> None:
        # Exercising to_thread.run_sync() triggers find_root_task(), which caches
        # the root task (and thus the loop) in the run-vars mapping.
        await to_thread.run_sync(thread_worker)
        loop_refs.append(weakref.ref(get_running_loop()))

    for _ in range(3):
        run(main, backend="asyncio")

    gc.collect()
    alive = [ref for ref in loop_refs if ref() is not None]
    assert not alive, f"{len(alive)} event loop(s) leaked"


def test_run_known_but_uninstalled_backend(monkeypatch: MonkeyPatch) -> None:
    async def main() -> None:
        pass

    monkeypatch.setattr("anyio._core._eventloop.BACKENDS", ("asyncio", "somebackend"))
    with pytest.raises(LookupError, match="pip install anyio\\[somebackend\\]"):
        run(main, backend="somebackend")


class TestAsyncioOptions:
    def test_debug(self) -> None:
        async def main() -> bool:
            return get_running_loop().get_debug()

        debug = run(main, backend="asyncio", backend_options={"debug": True})
        assert debug is True

    def test_debug_via_env(self, monkeypatch: MonkeyPatch) -> None:
        async def main() -> bool:
            return get_running_loop().get_debug()

        monkeypatch.setenv("PYTHONASYNCIODEBUG", "1")
        debug = run(main, backend="asyncio")
        assert debug is True

    def test_loop_factory(self) -> None:
        async def main() -> type:
            return type(get_running_loop())

        uvloop = pytest.importorskip("uvloop", reason="uvloop not installed")
        loop_class = run(
            main,
            backend="asyncio",
            backend_options={"loop_factory": uvloop.new_event_loop},
        )
        assert issubclass(loop_class, uvloop.Loop)

    def test_use_uvloop(self) -> None:
        async def main() -> type:
            return type(get_running_loop())

        uvloop = pytest.importorskip("uvloop", reason="uvloop not installed")
        loop_class = run(main, backend="asyncio", backend_options={"use_uvloop": True})
        assert issubclass(loop_class, uvloop.Loop)

    def test_use_winloop(self) -> None:
        async def main() -> type:
            return type(get_running_loop())

        winloop = pytest.importorskip("winloop", reason="winloop not installed")
        loop_class = run(main, backend="asyncio", backend_options={"use_uvloop": True})
        assert issubclass(loop_class, winloop.Loop)


class TestTrioOptions:
    def test_clock(self) -> None:
        """Test that ``backend_options`` are passed to ``trio.run()``."""
        try:
            from trio.testing import MockClock
        except ImportError:
            pytest.skip(reason="trio not installed")

        async def main() -> float:
            t1 = current_time()
            await sleep(10)
            return current_time() - t1

        rt1 = time.monotonic()
        trio_time = run(
            main,
            backend="trio",
            backend_options={"clock": MockClock(autojump_threshold=0)},
        )
        real_time = time.monotonic() - rt1
        assert real_time < 1
        assert trio_time == 10
