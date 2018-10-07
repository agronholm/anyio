import os
import signal

import pytest

from hyperio import receive_signals


@pytest.mark.skipif(os.name == 'nt', reason='Signal delivery cannot be tested on Windows')
@pytest.mark.hyperio
async def test_receive_signals():
    async with receive_signals(signal.SIGUSR1, signal.SIGUSR2) as sigiter:
        os.kill(os.getpid(), signal.SIGUSR1)
        os.kill(os.getpid(), signal.SIGUSR2)
        assert await sigiter.__anext__() == signal.SIGUSR1
        assert await sigiter.__anext__() == signal.SIGUSR2
