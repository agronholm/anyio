from __future__ import annotations

import os
import platform
import sys
from collections.abc import Callable
from contextlib import nullcontext
from functools import partial
from pathlib import Path
from subprocess import DEVNULL, PIPE, CalledProcessError
from textwrap import dedent
from typing import Any

import pytest
from pytest_mock.plugin import MockerFixture

import anyio.lowlevel
from anyio import (
    BrokenResourceError,
    CancelScope,
    ClosedResourceError,
    EndOfStream,
    Event,
    create_task_group,
    fail_after,
    get_cancelled_exc_class,
    open_process,
    run_process,
    sleep_forever,
)
from anyio._core._eventloop import get_async_backend
from anyio.abc import Process
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
                (
                    'import sys; print("stderr-text", file=sys.stderr); '
                    'print("stdout-text"); sys.exit(1)'
                ),
            ],
            check=True,
        )

    assert exc.value.returncode == 1
    assert exc.value.stdout.rstrip() == b"stdout-text"
    assert exc.value.stderr.rstrip() == b"stderr-text"


async def test_run_process_start() -> None:
    async with create_task_group() as tg:
        process = await tg.start(
            partial(
                run_process,
                [
                    sys.executable,
                    "-c",
                    "import sys; assert sys.stdin.read() == 'hello'",
                ],
                stdin=PIPE,
            )
        )
        assert isinstance(process, Process)
        assert process.pid > 0
        assert process.returncode is None
        assert process.stdin is not None
        await process.stdin.send(b"hello")
        await process.stdin.aclose()

    assert process.returncode == 0
    with pytest.raises(ClosedResourceError):
        await process.stdin.send(b"more")


async def test_run_process_start_before_sending_input(tmp_path: Path) -> None:
    """Starting must not wait for a child that is not ready to consume input yet."""
    ready_path = tmp_path / "ready"
    code = dedent("""\
        import os, sys, time

        while not os.path.exists(sys.argv[1]):
            time.sleep(0.01)

        assert sys.stdin.buffer.read() == b'x' * 1024 * 1024
    """)
    with fail_after(5):
        async with create_task_group() as tg:
            process = await tg.start(
                partial(
                    run_process,
                    [sys.executable, "-c", code, str(ready_path)],
                    input=b"x" * 1024 * 1024,
                )
            )
            assert process.returncode is None
            ready_path.touch()

    assert process.returncode == 0


@pytest.mark.parametrize("check", [False, True])
async def test_run_process_start_checked(check: bool) -> None:
    command = [
        sys.executable,
        "-c",
        "import sys; print('out'); print('err', file=sys.stderr); sys.exit(42)",
    ]
    raises = pytest.RaisesGroup(CalledProcessError)
    with raises if check else nullcontext() as exc:
        async with create_task_group() as tg:
            process = await tg.start(partial(run_process, command, check=check))

    assert process.returncode == 42
    if check:
        assert exc is not None
        error = exc.value.exceptions[0]
        assert isinstance(error, CalledProcessError)
        assert error.stdout.rstrip() == b"out"
        assert error.stderr.rstrip() == b"err"


async def test_run_process_start_failed(tmp_path: Path) -> None:
    async with create_task_group() as tg:
        with pytest.raises(FileNotFoundError):
            await tg.start(run_process, [str(tmp_path / "missing-executable")])


async def test_run_process_start_cancelled(mocker: MockerFixture) -> None:
    processes: list[Process] = []

    async def cancel_after_spawn(*args: Any, **kwargs: Any) -> Process:
        process = await open_process(*args, **kwargs)
        processes.append(process)
        scope.cancel()
        return process

    mocker.patch(
        "anyio._core._subprocesses.open_process", side_effect=cancel_after_spawn
    )
    with CancelScope() as scope:
        async with create_task_group() as tg:
            await tg.start(
                partial(
                    run_process,
                    [sys.executable, "-c", "import sys; sys.stdin.read()"],
                    stdin=PIPE,
                )
            )

    assert len(processes) == 1
    assert processes[0].returncode is not None
    assert processes[0].returncode != 0


@pytest.mark.parametrize("custom_cancel", [False, True])
async def test_run_process_start_cancel(custom_cancel: bool) -> None:
    cancelled_processes: list[Process] = []

    async def deliver_cancel(process: Process) -> None:
        cancelled_processes.append(process)
        await anyio.lowlevel.checkpoint()
        assert process.stdin is not None
        await process.stdin.send(b"stop\n")

    # The child must be able to finish writing even after cancellation has stopped
    # the original stdout/stderr readers.
    code = dedent("""\
        import sys

        assert sys.stdin.readline() == 'stop\\n'
        sys.stdout.buffer.write(b'x' * 1024 * 1024)
        sys.stderr.buffer.write(b'y' * 1024 * 1024)
    """)
    async with create_task_group() as tg:
        process = await tg.start(
            partial(
                run_process,
                [sys.executable, "-c", code],
                stdin=PIPE,
                deliver_cancel=deliver_cancel if custom_cancel else None,
            )
        )
        tg.cancel_scope.cancel()

    assert process.returncode is not None
    if custom_cancel:
        assert cancelled_processes == [process]
        assert process.returncode == 0
    else:
        assert cancelled_processes == []
        assert process.returncode != 0


async def test_run_process_cancel_callback_cancelled_on_exit() -> None:
    callback_finished = False

    async def deliver_cancel(process: Process) -> None:
        nonlocal callback_finished
        try:
            assert process.stdin is not None
            await process.stdin.send(b"stop\n")
            await sleep_forever()
        finally:
            callback_finished = True

    async with create_task_group() as tg:
        process = await tg.start(
            partial(
                run_process,
                [sys.executable, "-c", "import sys; sys.stdin.readline()"],
                stdin=PIPE,
                deliver_cancel=deliver_cancel,
            )
        )
        tg.cancel_scope.cancel()

    assert process.returncode == 0
    assert callback_finished


async def test_run_process_cancel_callback_error() -> None:
    async def deliver_cancel(process: Process) -> None:
        await anyio.lowlevel.checkpoint()
        raise RuntimeError("could not stop the child")

    with pytest.RaisesGroup(
        pytest.RaisesExc(RuntimeError, match="could not stop the child"),
        flatten_subgroups=True,
    ):
        async with create_task_group() as tg:
            process = await tg.start(
                partial(
                    run_process,
                    [sys.executable, "-c", "import sys; sys.stdin.read()"],
                    stdin=PIPE,
                    deliver_cancel=deliver_cancel,
                )
            )
            tg.cancel_scope.cancel()

    assert process.returncode is not None
    assert process.returncode != 0


async def test_run_process_cancel_callback_raises_cancellation() -> None:
    async def deliver_cancel(process: Process) -> None:
        cancelled_exc: BaseException | None = None
        with CancelScope() as scope:
            scope.cancel()
            try:
                await sleep_forever()
            except get_cancelled_exc_class() as exc:
                cancelled_exc = exc

        assert cancelled_exc is not None
        raise cancelled_exc

    async with create_task_group() as tg:
        process = await tg.start(
            partial(
                run_process,
                [sys.executable, "-c", "import sys; sys.stdin.read()"],
                stdin=PIPE,
                deliver_cancel=deliver_cancel,
            )
        )
        tg.cancel_scope.cancel()

    assert process.returncode is not None
    assert process.returncode != 0


async def test_run_process_cancel_direct_call(mocker: MockerFixture) -> None:
    process_started = Event()
    cancelled_processes: list[Process] = []

    async def signal_spawn(*args: Any, **kwargs: Any) -> Process:
        process = await open_process(*args, **kwargs)
        process_started.set()
        return process

    async def cancel_when_ready() -> None:
        await process_started.wait()
        scope.cancel()

    async def deliver_cancel(process: Process) -> None:
        cancelled_processes.append(process)
        assert process.stdin is not None
        await process.stdin.send(b"stop\n")

    mocker.patch("anyio._core._subprocesses.open_process", side_effect=signal_spawn)
    with fail_after(5), CancelScope() as scope:
        async with create_task_group() as tg:
            tg.start_soon(cancel_when_ready)
            await run_process(
                [
                    sys.executable,
                    "-c",
                    "import sys; assert sys.stdin.readline() == 'stop\\n'",
                ],
                stdin=PIPE,
                deliver_cancel=deliver_cancel,
            )

    assert len(cancelled_processes) == 1
    assert cancelled_processes[0].returncode == 0


@pytest.mark.parametrize("returncode", [0, 42])
async def test_run_process_no_cancellation(returncode: int) -> None:
    async def deliver_cancel(process: Process) -> None:
        pytest.fail("deliver_cancel() was called without cancellation")

    result = await run_process(
        [sys.executable, "-c", f"import sys; sys.exit({returncode})"],
        check=False,
        deliver_cancel=deliver_cancel,
    )
    assert result.returncode == returncode


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


@pytest.mark.parametrize("max_bytes", [0, -1])
async def test_process_receive_invalid_max_bytes(max_bytes: int) -> None:
    async with await open_process(
        [sys.executable, "-c", "import sys; sys.stdout.write('x')"]
    ) as process:
        assert process.stdout is not None
        with pytest.raises(ValueError, match="max_bytes must be a positive integer"):
            await process.stdout.receive(max_bytes)

        await process.wait()


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
                (
                    "import sys; txt = sys.stdin.read().strip(); "
                    'print("stdin says", repr(txt), "but stderr says NO!", '
                    "file=sys.stderr); "
                    'print("stdin says", repr(txt), "and stdout says YES!")'
                ),
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
                (
                    "import sys; txt = sys.stdin.read().strip(); "
                    'print("stdin says", repr(txt), "but stderr says NO!", '
                    "file=sys.stderr); "
                    'print("stdin says", repr(txt), "and stdout says YES!")'
                ),
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
        pytest.param("umask", lambda: 0, id="umask"),
    ],
)
async def test_user_group_arguments(
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


async def test_arguments_passed_through(mocker: MockerFixture) -> None:
    """
    Regression test ensuring all arguments accepted by ``open_process()``
    are passed through to the backend's ``open_process()``.
    """

    command = [sys.executable, "-c", "pass"]
    kwargs: dict[str, Any] = {
        "stdin": DEVNULL,
        "stdout": DEVNULL,
        "stderr": DEVNULL,
        "cwd": "/tmp",
        "env": {"FOO": "bar"},
        "startupinfo": object(),
        "creationflags": 4,
        "start_new_session": True,
        "pass_fds": (5, 6),
        "user": "myuser",
        "group": "mygroup",
        "extra_groups": [1, 2, "foo"],
        "umask": 123,
    }
    mock_open_process = mocker.patch.object(get_async_backend(), "open_process")
    await open_process(command, **kwargs)
    mock_open_process.assert_called_once_with(command, **kwargs)


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


async def test_wait_returns_on_process_exit_with_open_stdout() -> None:
    """
    wait() should return once the process exits, rather than waiting for the piped
    stdout/stderr to close. Easiest triggered by a grandchild that inherits the
    stdout pipe and keeps it open after the immediate child has exited.
    """
    code = dedent("""\
    import subprocess, sys

    subprocess.Popen(
        [sys.executable, "-c", "import select, sys; select.select([sys.stdin], [], [], 10)"]
    )
    """)

    process = await open_process([sys.executable, "-c", code])
    assert process.stdin is not None
    assert process.stdout is not None
    assert process.stderr is not None

    # Closing stdin unblocks the grandchild
    async with process.stdin:
        with fail_after(5):
            assert await process.wait() == 0

    # Wait for grandchild to exit to avoid ResourceWarnings
    with fail_after(3, shield=True):
        async for _ in process.stdout:
            pass

        async for _ in process.stderr:
            pass


async def test_close_with_stdout_blocked_subprocess(anyio_backend_name: str) -> None:
    """
    Regression test for #1166.

    Test that closing a process unblocks a subprocess blocked on writing to stdout
    (because the pipe buffer is full and nobody is reading), instead of deadlocking
    while waiting for it to exit.
    """

    process = await open_process(
        [sys.executable, "-c", "import sys;sys.stdout.write('x' * 1024 * 1024)"]
    )
    try:
        with fail_after(5):
            await process.aclose()
    except TimeoutError:
        if anyio_backend_name == "asyncio":
            process._process._transport.close()  # type: ignore[attr-defined]

        pytest.fail("Process.aclose() deadlocked")
