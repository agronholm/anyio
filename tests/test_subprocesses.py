import os
import platform
import sys
import time
from functools import partial
from subprocess import CalledProcessError
from textwrap import dedent

import pytest

from anyio import (
    CancelScope, create_task_group, fail_after, open_process, run_process, run_sync_in_process,
    wait_all_tasks_blocked)
from anyio._core._subprocesses import _process_pool_workers
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

    async def test_identical_sys_path(self):
        """Test that partial() can be used to pass keyword arguments."""
        assert await run_sync_in_process(eval, 'sys.path') == sys.path

    async def test_partial(self):
        """Test that partial() can be used to pass keyword arguments."""
        assert await run_sync_in_process(partial(sorted, reverse=True), ['a', 'b']) == ['b', 'a']

    async def test_exception(self):
        """Test that exceptions are delivered properly."""
        with pytest.raises(ValueError, match='invalid literal for int'):
            assert await run_sync_in_process(int, 'a')

    async def test_print(self):
        """Test that print() won't interfere with parent-worker communication."""
        worker_pid = await run_sync_in_process(os.getpid)
        await run_sync_in_process(print, 'hello')
        await run_sync_in_process(print, 'world')
        assert await run_sync_in_process(os.getpid) == worker_pid

    async def test_cancel_before(self):
        """
        Test that starting run_sync_in_process() in a cancelled scope does not cause a worker
        process to be reserved.

        """
        with CancelScope() as scope:
            scope.cancel()
            await run_sync_in_process(os.getpid)

        pytest.raises(LookupError, _process_pool_workers.get)

    async def test_cancel_during(self):
        """
        Test that cancelling an operation on the worker process causes the process to be killed.

        """
        worker_pid = await run_sync_in_process(os.getpid)
        with fail_after(4):
            async with create_task_group() as tg:
                tg.spawn(partial(run_sync_in_process, cancellable=True), time.sleep, 5)
                await wait_all_tasks_blocked()
                tg.cancel_scope.cancel()

        # The previous worker was killed so we should get a new one now
        assert await run_sync_in_process(os.getpid) != worker_pid
