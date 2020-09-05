import platform
import sys
from subprocess import CalledProcessError
from textwrap import dedent

import pytest

from anyio import open_process, run_process
from anyio.streams.buffered import BufferedByteReceiveStream

pytestmark = pytest.mark.anyio


@pytest.fixture(autouse=True)
def check_compatibility(anyio_backend_name):
    if anyio_backend_name == 'curio':
        if platform.python_implementation() == 'PyPy':
            pytest.skip('Using subprocesses causes Curio to crash PyPy')
        elif platform.system() == 'Windows':
            pytest.skip('Subprocess support on Curio+Windows is broken')
    elif anyio_backend_name == 'asyncio':
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
    if anyio_backend_name == 'curio' and platform.python_implementation() == 'PyPy':
        pytest.skip('This test causes Curio to crash PyPy')

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
