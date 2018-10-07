import os
import signal
import sys

import pytest

from anyio import receive_signals, run_in_thread


@pytest.mark.skipif(sys.platform == 'win32', reason='Signal delivery cannot be tested on Windows')
@pytest.mark.anyio
async def test_receive_signals():
    async with receive_signals(signal.SIGUSR1, signal.SIGUSR2) as sigiter:
        await run_in_thread(os.kill, os.getpid(), signal.SIGUSR1)
        await run_in_thread(os.kill, os.getpid(), signal.SIGUSR2)
        assert await sigiter.__anext__() == signal.SIGUSR1
        assert await sigiter.__anext__() == signal.SIGUSR2
