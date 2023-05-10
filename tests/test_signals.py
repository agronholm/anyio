from __future__ import annotations

import os
import signal
import sys
from typing import AsyncIterable

import pytest

from anyio import create_task_group, fail_after, open_signal_receiver, to_thread

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="Signal delivery cannot be tested on Windows",
    ),
]


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


async def test_task_group_cancellation_open() -> None:
    async def signal_handler() -> None:
        with open_signal_receiver(signal.SIGUSR1) as sigiter:
            async for v in sigiter:
                pytest.fail("SIGUSR1 should not be sent")

            pytest.fail("signal_handler should have been cancelled")

        pytest.fail("open_signal_receiver should not suppress cancellation")

    async with create_task_group() as tg:
        tg.start_soon(signal_handler)
        tg.cancel_scope.cancel()


async def test_task_group_cancellation_consume() -> None:
    async def consume(sigiter: AsyncIterable[int]) -> None:
        async for v in sigiter:
            pytest.fail("SIGUSR1 should not be sent")

        pytest.fail("consume should have been cancelled")

    with open_signal_receiver(signal.SIGUSR1) as sigiter:
        async with create_task_group() as tg:
            tg.start_soon(consume, sigiter)
            tg.cancel_scope.cancel()
