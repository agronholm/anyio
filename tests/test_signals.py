from __future__ import annotations

import asyncio
import os
import signal
import sys
from collections.abc import AsyncIterable

import pytest

from anyio import (
    create_task_group,
    fail_after,
    open_signal_receiver,
    to_thread,
    wait_all_tasks_blocked,
)

pytestmark = [
    # Workaround for https://github.com/MagicStack/uvloop/issues/703
    pytest.mark.filterwarnings(
        "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning"
    ),
]

skip_no_signal_delivery = pytest.mark.skipif(
    sys.platform == "win32",
    reason="Signal delivery cannot be tested on Windows",
)


@skip_no_signal_delivery
async def test_receive_signals() -> None:
    with open_signal_receiver(signal.SIGUSR1, signal.SIGUSR2) as sigiter:
        await to_thread.run_sync(os.kill, os.getpid(), signal.SIGUSR1)
        await to_thread.run_sync(os.kill, os.getpid(), signal.SIGUSR2)
        with fail_after(1):
            sigusr1 = await sigiter.__anext__()
            assert isinstance(sigusr1, signal.Signals)
            assert sigusr1 == signal.Signals.SIGUSR1

            sigusr2 = await sigiter.__anext__()
            assert isinstance(sigusr2, signal.Signals)
            assert sigusr2 == signal.Signals.SIGUSR2


@skip_no_signal_delivery
async def test_task_group_cancellation_open() -> None:
    async def signal_handler() -> None:
        with open_signal_receiver(signal.SIGUSR1) as sigiter:
            async for _ in sigiter:
                pytest.fail("SIGUSR1 should not be sent")

            pytest.fail("signal_handler should have been cancelled")

        pytest.fail("open_signal_receiver should not suppress cancellation")

    async with create_task_group() as tg:
        tg.start_soon(signal_handler)
        tg.cancel_scope.cancel()


@skip_no_signal_delivery
async def test_task_group_cancellation_consume() -> None:
    async def consume(sigiter: AsyncIterable[int]) -> None:
        async for _ in sigiter:
            pytest.fail("SIGUSR1 should not be sent")

        pytest.fail("consume should have been cancelled")

    with open_signal_receiver(signal.SIGUSR1) as sigiter:
        async with create_task_group() as tg:
            tg.start_soon(consume, sigiter)
            tg.cancel_scope.cancel()


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_concurrent_iterators_receive_distinct_signals(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Two tasks iterating the same signal receiver each get their own signal."""
    handlers: dict[signal.Signals, object] = {}

    def fake_add_signal_handler(
        sig: signal.Signals, callback: object, *args: object
    ) -> None:
        handlers[sig] = lambda: callback(*args)  # type: ignore[operator]

    loop = asyncio.get_running_loop()
    monkeypatch.setattr(loop, "add_signal_handler", fake_add_signal_handler)
    monkeypatch.setattr(loop, "remove_signal_handler", lambda sig: None)

    received: list[signal.Signals] = []

    async def consume() -> None:
        received.append(await sigiter.__anext__())

    with open_signal_receiver(signal.SIGINT, signal.SIGTERM) as sigiter:
        with fail_after(1):
            async with create_task_group() as tg:
                tg.start_soon(consume)
                tg.start_soon(consume)
                await wait_all_tasks_blocked()
                assert set(handlers) == {signal.SIGINT, signal.SIGTERM}
                # Simulate the OS delivering both signals
                handlers[signal.SIGINT]()
                handlers[signal.SIGTERM]()

    assert sorted(received) == [signal.SIGINT, signal.SIGTERM]
