import os
import signal
import sys

import pytest

from anyio import create_task_group, fail_after, open_signal_receiver, to_thread

pytestmark = [
    pytest.mark.anyio,
    pytest.mark.skipif(
        sys.platform == 'win32',
        reason='Signal delivery cannot be tested on Windows',
    ),
]


async def test_receive_signals():
    with open_signal_receiver(signal.SIGUSR1, signal.SIGUSR2) as sigiter:
        await to_thread.run_sync(os.kill, os.getpid(), signal.SIGUSR1)
        await to_thread.run_sync(os.kill, os.getpid(), signal.SIGUSR2)
        with fail_after(1):
            assert await sigiter.__anext__() == signal.SIGUSR1
            assert await sigiter.__anext__() == signal.SIGUSR2


async def test_task_group_cancellation_open():
    async def signal_handler():
        with open_signal_receiver(signal.SIGUSR1) as sigiter:
            async for v in sigiter:
                pytest.fail("SIGUSR1 should not be sent")

            pytest.fail("signal_handler should have been cancelled")

        pytest.fail("open_signal_receiver should not suppress cancellation")

    async with create_task_group() as tg:
        tg.start_soon(signal_handler)
        tg.cancel_scope.cancel()


async def test_task_group_cancellation_consume():
    async def consume(sigiter):
        async for v in sigiter:
            pytest.fail("SIGUSR1 should not be sent")

        pytest.fail("consume should have been cancelled")

    with open_signal_receiver(signal.SIGUSR1) as sigiter:
        async with create_task_group() as tg:
            tg.start_soon(consume, sigiter)
            tg.cancel_scope.cancel()
