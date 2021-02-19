import os
import signal
import sys

import pytest

from anyio import create_task_group, fail_after, open_signal_receiver, run_sync_in_worker_thread

pytestmark = pytest.mark.anyio


@pytest.mark.skipif(sys.platform == 'win32', reason='Signal delivery cannot be tested on Windows')
async def test_receive_signals():
    async with open_signal_receiver(signal.SIGUSR1, signal.SIGUSR2) as sigiter:
        await run_sync_in_worker_thread(os.kill, os.getpid(), signal.SIGUSR1)
        await run_sync_in_worker_thread(os.kill, os.getpid(), signal.SIGUSR2)
        async with fail_after(1):
            assert await sigiter.__anext__() == signal.SIGUSR1
            assert await sigiter.__anext__() == signal.SIGUSR2


@pytest.mark.skipif(sys.platform == 'win32', reason='Signal delivery cannot be tested on Windows')
async def test_task_group_cancellation():
    async def signal_handler():
        async with open_signal_receiver(signal.SIGUSR1) as sigiter:
            async for v in sigiter:
                assert False

    async with create_task_group() as tg:
        await tg.spawn(signal_handler)
        await tg.cancel_scope.cancel()
