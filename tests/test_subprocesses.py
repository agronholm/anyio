from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from pathlib import Path
from subprocess import CalledProcessError
from textwrap import dedent
from typing import Any

import pytest

from anyio import (
    BrokenResourceError,
    CancelScope,
    ClosedResourceError,
    EndOfStream,
    create_task_group,
    open_process,
    run_process,
)
from anyio.streams.buffered import BufferedByteReceiveStream


@pytest.mark.parametrize(
    "shell, command",
    [
        pytest.param(
            True,
            f'{sys.executable} -c "import sys; print(sys.stdin.read()[::-1])"',
            id="shell",
        ),
        pytest.param(
            False,
            [sys.executable, "-c", "import sys; print(sys.stdin.read()[::-1])"],
            id="exec",
        ),
    ],
)
async def test_run_process(
    shell: bool, command: str | list[str], event_loop_implementation_name: str | None
) -> None:
    if event_loop_implementation_name == "winloop":
        pytest.skip(reason="winloop produces a non-zero exit with status 1")

    process = await run_process(command, input=b"abc")
    assert process.returncode == 0
    assert process.stdout.rstrip() == b"cba"


async def test_run_process_checked() -> None:
    with pytest.raises(CalledProcessError) as exc:
        await run_process(
            [
                sys.executable,
                "-c",
                'import sys; print("stderr-text", file=sys.stderr); '
                'print("stdout-text"); sys.exit(1)',
            ],
            check=True,
        )

    assert exc.value.returncode == 1
    assert exc.value.stdout.rstrip() == b"stdout-text"
    assert exc.value.stderr.rstrip() == b"stderr-text"


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="process.terminate() kills the process instantly on Windows",
)
async def test_terminate(tmp_path: Path) -> None:
    script_path = tmp_path / "script.py"
    script_path.write_text(
        dedent(
            """\
        import signal, sys, time

        def terminate(signum, frame):
            sys.exit(2)

        signal.signal(signal.SIGTERM, terminate)
        print('ready', flush=True)
        time.sleep(5)
    """
        )
    )
    async with await open_process([sys.executable, str(script_path)]) as process:
        stdout = process.stdout
        assert stdout is not None
        buffered_stdout = BufferedByteReceiveStream(stdout)
        line = await buffered_stdout.receive_until(b"\n", 100)
        assert line.rstrip() == b"ready"

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


@pytest.mark.skipif(
    platform.system() == "Windows", reason="Windows does not have os.getsid()"
)
async def test_process_new_session_sid() -> None:
    """
    Test that start_new_session is successfully passed to the subprocess implementation.

    """
    sid = os.getsid(os.getpid())
    cmd = [sys.executable, "-c", "import os; print(os.getsid(os.getpid()))"]

    result = await run_process(cmd)
    assert result.stdout.decode().strip() == str(sid)

    result = await run_process(cmd, start_new_session=True)
    assert result.stdout.decode().strip() != str(sid)


async def test_open_process_connect_to_file(tmp_path: Path) -> None:
    stdinfile = tmp_path / "stdin"
    stdinfile.write_text("Hello, process!\n")
    stdoutfile = tmp_path / "stdout"
    stderrfile = tmp_path / "stderr"
    with (
        stdinfile.open("rb") as fin,
        stdoutfile.open("wb") as fout,
        stderrfile.open("wb") as ferr,
    ):
        async with await open_process(
            [
                sys.executable,
                "-c",
                "import sys; txt = sys.stdin.read().strip(); "
                'print("stdin says", repr(txt), "but stderr says NO!", '
                "file=sys.stderr); "
                'print("stdin says", repr(txt), "and stdout says YES!")',
            ],
            stdin=fin,
            stdout=fout,
            stderr=ferr,
        ) as p:
            assert await p.wait() == 0

    assert (
        stdoutfile.read_text() == "stdin says 'Hello, process!' and stdout says YES!\n"
    )
    assert (
        stderrfile.read_text() == "stdin says 'Hello, process!' but stderr says NO!\n"
    )


async def test_run_process_connect_to_file(tmp_path: Path) -> None:
    stdinfile = tmp_path / "stdin"
    stdinfile.write_text("Hello, process!\n")
    stdoutfile = tmp_path / "stdout"
    stderrfile = tmp_path / "stderr"
    with (
        stdinfile.open("rb") as fin,
        stdoutfile.open("wb") as fout,
        stderrfile.open("wb") as ferr,
    ):
        await run_process(
            [
                sys.executable,
                "-c",
                "import sys; txt = sys.stdin.read().strip(); "
                'print("stdin says", repr(txt), "but stderr says NO!", '
                "file=sys.stderr); "
                'print("stdin says", repr(txt), "and stdout says YES!")',
            ],
            stdin=fin,
            stdout=fout,
            stderr=ferr,
        )

    assert (
        stdoutfile.read_text() == "stdin says 'Hello, process!' and stdout says YES!\n"
    )
    assert (
        stderrfile.read_text() == "stdin says 'Hello, process!' but stderr says NO!\n"
    )


async def test_stdin_input_both_passed(tmp_path: Path) -> None:
    stdinfile = tmp_path / "stdin"
    stdinfile.write_text("Hello, process!\n")
    with pytest.raises(ValueError, match="only one of"), stdinfile.open("rb") as fin:
        await run_process([sys.executable, "--version"], input=b"abc", stdin=fin)


async def test_run_process_inherit_stdout(capfd: pytest.CaptureFixture[str]) -> None:
    await run_process(
        [
            sys.executable,
            "-c",
            'import sys; print("stderr-text", file=sys.stderr); print("stdout-text")',
        ],
        check=True,
        stdout=None,
        stderr=None,
    )
    out, err = capfd.readouterr()
    assert out == "stdout-text" + os.linesep
    assert err == "stderr-text" + os.linesep


async def test_process_aexit_cancellation_doesnt_orphan_process() -> None:
    """
    Regression test for #669.

    Ensures that open_process.__aexit__() doesn't leave behind an orphan process when
    cancelled.

    """
    with CancelScope() as scope:
        async with await open_process(
            [sys.executable, "-c", "import time; time.sleep(1)"]
        ) as process:
            scope.cancel()

    assert process.returncode is not None
    assert process.returncode != 0


async def test_process_aexit_cancellation_closes_standard_streams() -> None:
    """
    Regression test for #669.

    Ensures that open_process.__aexit__() closes standard streams when cancelled. Also
    ensures that process.std{in.send,{out,err}.receive}() raise ClosedResourceError on a
    closed stream.

    """
    with CancelScope() as scope:
        async with await open_process(
            [sys.executable, "-c", "import time; time.sleep(1)"]
        ) as process:
            scope.cancel()

    assert process.stdin is not None

    with pytest.raises(ClosedResourceError):
        await process.stdin.send(b"foo")

    assert process.stdout is not None

    with pytest.raises(ClosedResourceError):
        await process.stdout.receive(1)

    assert process.stderr is not None

    with pytest.raises(ClosedResourceError):
        await process.stderr.receive(1)


async def test_exceptions_after_subprocess_closes_standard_streams() -> None:
    async with await open_process([sys.executable, "-c", ""]) as process:
        await process.wait()
        assert process.stdin is not None
        assert process.stderr is not None
        assert process.stdout is not None
        with pytest.raises(BrokenResourceError):
            # * On Trio, stdin.send() will always raise if the peer's end of the pipe is
            #   closed.
            # * On asyncio, even though process.wait() finished, some event loop
            #   implementations do not yet inform us that the peer's end of the pipe is
            #   closed; the event loop needs to run some rounds of callbacks before it
            #   will get that information to us. In particular:
            #   * On stdlib asyncio, stdin.send() will now always raise
            #     BrokenResourceError.
            #   * On uvloop, the second stdin.send() will raise BrokenResourceError.
            #   * On Winloop 0.3.0, the third stdin.send() will raise
            #     BrokenResourceError. The second also might, but it depends on
            #     scheduling order.
            #   * On Winloop 0.3.1, the second stdin() will raise BrokenResourceError.
            for _ in range(3):
                await process.stdin.send(b"foo")

        with pytest.raises(BrokenResourceError):
            await process.stdin.send(b"foo")

        with pytest.raises(EndOfStream):
            await process.stdout.receive(1)

        with pytest.raises(EndOfStream):
            await process.stderr.receive(1)

    with pytest.raises(ClosedResourceError):
        await process.stdin.send(b"foo")

    with pytest.raises(ClosedResourceError):
        await process.stdout.receive(1)

    with pytest.raises(ClosedResourceError):
        await process.stderr.receive(1)


@pytest.mark.parametrize(
    "argname, argvalue_factory",
    [
        pytest.param(
            "user",
            lambda: os.getuid(),
            id="user",
            marks=[
                pytest.mark.skipif(
                    platform.system() == "Windows",
                    reason="os.getuid() is not available on Windows",
                )
            ],
        ),
        pytest.param(
            "group",
            lambda: os.getgid(),
            id="user",
            marks=[
                pytest.mark.skipif(
                    platform.system() == "Windows",
                    reason="os.getgid() is not available on Windows",
                )
            ],
        ),
        pytest.param("extra_groups", list, id="extra_groups"),
        pytest.param("umask", lambda: 0, id="umask"),
    ],
)
async def test_py39_arguments(
    argname: str,
    argvalue_factory: Callable[[], Any],
    event_loop_implementation_name: str | None,
) -> None:
    try:
        await run_process(
            [sys.executable, "-c", "print('hello')"],
            **{argname: argvalue_factory()},
        )
    except ValueError as exc:
        if "unexpected kwargs" in str(exc) and event_loop_implementation_name in (
            "uvloop",
            "winloop",
        ):
            pytest.skip(
                f"the {argname!r} argument is not supported by "
                f"{event_loop_implementation_name} yet"
            )

        raise


async def test_close_early() -> None:
    """Regression test for #490."""
    code = dedent("""\
    import sys
    for _ in range(100):
        sys.stdout.buffer.write(bytes(range(256)))
    """)

    async with await open_process([sys.executable, "-c", code]):
        pass


async def test_close_while_reading() -> None:
    code = dedent("""\
    import time

    time.sleep(3)
    """)

    async with (
        await open_process([sys.executable, "-c", code]) as process,
        create_task_group() as tg,
    ):
        assert process.stdout
        tg.start_soon(process.stdout.aclose)
        with pytest.raises(ClosedResourceError):
            await process.stdout.receive()

        process.terminate()


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Unix-specific: grandchild process and signal handling",
)
async def test_wait_returns_on_process_exit_with_open_stdout() -> None:
    """wait() should return once the process exits, even when a grandchild
    keeps a pipe file descriptor open."""

    code = dedent("""\
    import subprocess, sys

    subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sys.stdout.write("ok")
    """)

    async with await open_process([sys.executable, "-c", code]) as process:
        returncode = await process.wait()

    assert returncode == 0


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Unix-specific: pipe buffer sizes and EPIPE behaviour",
)
async def test_aclose_unblocks_subprocess_blocked_on_write() -> None:
    """aclose() must unblock a subprocess that is stuck writing to a full
    pipe (because nobody is reading), rather than deadlocking while waiting
    for it to exit."""

    # Write enough data to fill the pipe buffer (~64 KiB on Linux) so the
    # subprocess blocks and never reaches its own exit.
    code = dedent("""\
    import sys

    sys.stdout.write("x" * 1024 * 1024)
    sys.stdout.flush()
    """)

    from anyio import Event, sleep

    deadline_hit = Event()

    async with create_task_group() as tg:
        process = await open_process([sys.executable, "-c", code])

        async def deadline() -> None:
            await sleep(5)
            deadline_hit.set()

        tg.start_soon(deadline)

        # This must not deadlock even though the subprocess is still
        # blocked on the full stdout pipe.
        await process.aclose()
        tg.cancel_scope.cancel()

    assert not deadline_hit.is_set(), "Process.aclose() deadlocked"


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Unix-specific: pipe buffer sizes and EPIPE behaviour",
)
async def test_wait_returns_when_subprocess_blocked_on_write() -> None:
    """wait() must not deadlock when a subprocess is stuck writing to a
    full pipe.  It should return the exit code once aclose() closes the
    pipes and terminates the process."""

    code = dedent("""\
    import sys

    sys.stdout.write("x" * 1024 * 1024)
    sys.stdout.flush()
    """)

    from anyio import Event, sleep

    deadline_hit = Event()

    async with create_task_group() as tg:
        process = await open_process([sys.executable, "-c", code])

        async def deadline() -> None:
            await sleep(5)
            deadline_hit.set()

        tg.start_soon(deadline)

        # Close pipes and kill the process so it exits, then wait() must
        # return promptly rather than hanging on the still-full pipe.
        await process.aclose()
        tg.cancel_scope.cancel()

    returncode = await process.wait()
    assert not deadline_hit.is_set(), "Process.wait() deadlocked"
    assert returncode is not None  # process exited


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Unix-specific: pipe buffer sizes and EPIPE behaviour",
)
async def test_wait_returns_promptly_for_fast_exit() -> None:
    """wait() must return quickly when the process exits immediately
    without writing to stdout or stderr."""

    from anyio import Event, sleep

    deadline_hit = Event()

    async with create_task_group() as tg:
        process = await open_process([sys.executable, "-c", ""])

        async def deadline() -> None:
            await sleep(5)
            deadline_hit.set()

        tg.start_soon(deadline)

        returncode = await process.wait()
        tg.cancel_scope.cancel()

    assert not deadline_hit.is_set(), "Process.wait() deadlocked for fast exit"
    assert returncode == 0


@pytest.mark.skipif(
    platform.system() == "Windows",
    reason="Unix-specific: grandchild process and signal handling",
)
async def test_wait_returns_on_process_exit_with_open_stderr() -> None:
    """wait() should return once the process exits, even when a grandchild
    keeps the stderr pipe file descriptor open."""

    code = dedent("""\
    import subprocess, sys

    subprocess.Popen(
        [sys.executable, "-c", "import time; time.sleep(10)"],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
    )
    sys.stderr.write("ok")
    """)

    async with await open_process([sys.executable, "-c", code]) as process:
        returncode = await process.wait()

    assert returncode == 0
