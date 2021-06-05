import os
import platform
import sys
from pathlib import Path
from subprocess import CalledProcessError
from textwrap import dedent
from typing import List, Union

import pytest

from anyio import open_process, run_process
from anyio.streams.buffered import BufferedByteReceiveStream

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def check_compatibility(anyio_backend_name: str) -> None:
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
async def test_run_process(shell: bool, command: Union[str, List[str]],
                           anyio_backend_name: str) -> None:
    process = await run_process(command, input=b'abc')
    assert process.returncode == 0
    assert process.stdout.rstrip() == b'cba'


async def test_run_process_checked() -> None:
    with pytest.raises(CalledProcessError) as exc:
        await run_process([sys.executable, '-c',
                           'import sys; print("stderr-text", file=sys.stderr); '
                           'print("stdout-text"); sys.exit(1)'], check=True)

    assert exc.value.returncode == 1
    assert exc.value.stdout.rstrip() == b'stdout-text'
    assert exc.value.stderr.rstrip() == b'stderr-text'


@pytest.mark.skipif(platform.system() == 'Windows',
                    reason='process.terminate() kills the process instantly on Windows')
async def test_terminate(tmp_path: Path) -> None:
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
        stdout = process.stdout
        assert stdout is not None
        buffered_stdout = BufferedByteReceiveStream(stdout)
        line = await buffered_stdout.receive_until(b'\n', 100)
        assert line.rstrip() == b'ready'

        process.terminate()
        assert await process.wait() == 2


async def test_process_cwd(tmp_path: Path) -> None:
    """Test that `cwd` is successfully passed to the subprocess implementation"""
    cmd = [sys.executable, "-c", "import os; print(os.getcwd())"]
    result = await run_process(cmd, cwd=tmp_path)
    assert result.stdout.decode().strip() == str(tmp_path)


async def test_process_env() -> None:
    """Test that `env` is successfully passed to the subprocess implementation"""
    env = os.environ.copy()
    env.update({"foo": "bar"})
    cmd = [sys.executable, "-c", "import os; print(os.environ['foo'])"]
    result = await run_process(cmd, env=env)
    assert result.stdout.decode().strip() == env["foo"]
