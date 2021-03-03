import os
import platform
import signal
import sys
from subprocess import CalledProcessError
from textwrap import dedent

import pytest

from anyio import BrokenWorkerProcess, open_process, run_process, run_sync_in_process
from anyio.streams.buffered import BufferedByteReceiveStream

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def check_compatibility(anyio_backend_name):
    if anyio_backend_name == 'asyncio':
        if platform.system() == 'Windows' and sys.version_info < (3, 8):
            pytest.skip('Python < 3.8 uses SelectorEventLoop by default and it does not support '
                        'subprocesses')


@pytest.mark.parametrize('shell, command', [
    pytest.param(True, f'{sys.executable} -c "import sys; print(sys.stdin.read()[::-1])"',
                 id='shell'),
    pytest.param(False, [sys.executable, '-c', 'import sys; print(sys.stdin.read()[::-1])'],
                 id='exec')
])
async def test_run_process(shell, command, anyio_backend_name):
    process = await run_process(command, input=b'abc')
    assert process.returncode == 0
    assert process.stdout.rstrip() == b'cba'


async def test_run_process_checked():
    with pytest.raises(CalledProcessError) as exc:
        await run_process([sys.executable, '-c',
                           'import sys; print("stderr-text", file=sys.stderr); '
                           'print("stdout-text"); sys.exit(1)'], check=True)

    assert exc.value.returncode == 1
    assert exc.value.stdout.rstrip() == b'stdout-text'
    assert exc.value.stderr.rstrip() == b'stderr-text'


@pytest.mark.skipif(platform.system() == 'Windows',
                    reason='process.terminate() kills the process instantly on Windows')
async def test_terminate(tmp_path):
    script_path = tmp_path / 'script.py'
    script_path.write_text(dedent("""\
        import signal, sys, time

        def terminate(signum, frame):
            sys.exit(2)

        signal.signal(signal.SIGTERM, terminate)
        print('ready', flush=True)
        time.sleep(5)
    """))
    async with await open_process([sys.executable, str(script_path)]) as process:
        buffered_stdout = BufferedByteReceiveStream(process.stdout)
        line = await buffered_stdout.receive_until(b'\n', 100)
        assert line.rstrip() == b'ready'

        process.terminate()
        assert await process.wait() == 2


class TestProcessPool:
    async def test_run_sync_in_process_pool(self):
        """
        Test that the function runs in a different process, and the same process in both calls.
        """
        worker_pid = await run_sync_in_process(os.getpid)
        assert worker_pid != os.getpid()
        assert await run_sync_in_process(os.getpid) == worker_pid

    async def test_exception(self):
        """Test that exceptions are delivered properly."""
        with pytest.raises(ValueError, match='invalid literal for int'):
            assert await run_sync_in_process(int, 'a')

    async def test_unexpected_worker_exit(self):
        """Test that an unexpected worker exit is handled correctly."""
        worker_pid = await run_sync_in_process(os.getpid)
        os.kill(worker_pid, signal.SIGKILL)
        with pytest.raises(BrokenWorkerProcess):
            await run_sync_in_process(os.getpid)
