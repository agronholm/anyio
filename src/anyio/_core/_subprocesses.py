from __future__ import annotations

import math
import os
import subprocess
import sys
from collections.abc import AsyncIterable, Iterable, Mapping, Sequence
from functools import partial
from io import BytesIO
from os import PathLike
from signal import Signals
from subprocess import PIPE, CalledProcessError, CompletedProcess
from typing import IO, Any, TypeAlias, cast

from ..abc import ByteReceiveStream, ByteSendStream, Process
from ..lowlevel import RunVar
from ._eventloop import get_async_backend
from ._synchronization import CapacityLimiter, Lock
from ._tasks import CancelScope, create_task_group

StrOrBytesPath: TypeAlias = str | bytes | PathLike[str] | PathLike[bytes]

# A dedicated, unbounded limiter for the (potentially long-lived) child-reaping worker
# threads, so that they don't starve the default thread limiter.
_child_reaper_limiter: RunVar[CapacityLimiter] = RunVar("_child_reaper_limiter")


def _get_child_reaper_limiter() -> CapacityLimiter:
    try:
        return _child_reaper_limiter.get()
    except LookupError:
        limiter = CapacityLimiter(math.inf)
        _child_reaper_limiter.set(limiter)
        return limiter


def _sync_wait_for_exit(process: subprocess.Popen[bytes]) -> None:
    """
    Block (in a worker thread) until ``process`` has exited.

    Where ``os.waitid()`` is available (Linux, and macOS on Python 3.13+), this uses
    ``WNOWAIT`` so the exit status is left intact for :meth:`subprocess.Popen.wait`.
    Otherwise it falls back to :meth:`subprocess.Popen.wait`, which reaps the process
    directly (that's fine, since the shared ``Process.wait()`` calls it again).
    """
    if hasattr(os, "waitid"):
        while True:
            try:
                os.waitid(os.P_PID, process.pid, os.WEXITED | os.WNOWAIT)
            except InterruptedError:
                continue
            except ChildProcessError:
                # Already reaped elsewhere
                return
            else:
                return

    process.wait()


async def wait_for_child_exit(process: subprocess.Popen[bytes]) -> None:
    """
    Backend-agnostic POSIX implementation of
    :meth:`~anyio.abc.AsyncBackend.wait_for_child_exit`.

    On Linux this waits on a pidfd, without tying up a worker thread. On other POSIX
    systems it waits in a worker thread (see :func:`_sync_wait_for_exit`).
    """
    backend = get_async_backend()
    if sys.platform == "linux" and hasattr(os, "pidfd_open"):
        try:
            pidfd = os.pidfd_open(process.pid)
        except OSError:
            pass
        else:
            try:
                await backend.wait_readable(pidfd)
            finally:
                os.close(pidfd)

            return

    await backend.run_sync_in_worker_thread(
        _sync_wait_for_exit,
        (process,),
        abandon_on_cancel=True,
        limiter=_get_child_reaper_limiter(),
    )


class _Process(Process):
    """
    A backend-agnostic :class:`~anyio.abc.Process` implementation.

    The process itself is spawned via :class:`subprocess.Popen`; its standard streams and
    the waiting for its exit are provided by small, backend-specific primitives
    (:meth:`~anyio.abc.AsyncBackend.create_subprocess_stdin_pipe`,
    :meth:`~anyio.abc.AsyncBackend.create_subprocess_output_pipe` and
    :meth:`~anyio.abc.AsyncBackend.wait_for_child_exit`). This lifecycle logic is
    therefore shared between all backends.
    """

    def __init__(
        self,
        popen: subprocess.Popen,
        stdin: ByteSendStream | None,
        stdout: ByteReceiveStream | None,
        stderr: ByteReceiveStream | None,
    ) -> None:
        self._popen = popen
        self._stdin = stdin
        self._stdout = stdout
        self._stderr = stderr
        self._wait_lock = Lock()

    async def aclose(self) -> None:
        with CancelScope(shield=True) as scope:
            if self._stdin:
                await self._stdin.aclose()
            if self._stdout:
                await self._stdout.aclose()
            if self._stderr:
                await self._stderr.aclose()

            scope.shield = False
            try:
                await self.wait()
            except BaseException:
                scope.shield = True
                self.kill()
                await self.wait()
                raise

    async def wait(self) -> int:
        async with self._wait_lock:
            if self._popen.poll() is None:
                await get_async_backend().wait_for_child_exit(self._popen)
                # The exit status hasn't been consumed yet, so this returns immediately
                self._popen.wait()

        return cast(int, self._popen.returncode)

    def terminate(self) -> None:
        if self._popen.poll() is not None:
            return
        try:
            self._popen.terminate()
        except ProcessLookupError:
            pass

    def kill(self) -> None:
        if self._popen.poll() is not None:
            return
        try:
            self._popen.kill()
        except ProcessLookupError:
            pass

    def send_signal(self, signal: Signals) -> None:
        if self._popen.poll() is not None:
            return
        try:
            self._popen.send_signal(signal)
        except ProcessLookupError:
            pass

    @property
    def pid(self) -> int:
        return self._popen.pid

    @property
    def returncode(self) -> int | None:
        # Poll so that the return code is up to date even if wait() hasn't been called
        # yet (this matches the Trio backend's historical behavior, see discussion #828)
        return self._popen.poll()

    @property
    def stdin(self) -> ByteSendStream | None:
        return self._stdin

    @property
    def stdout(self) -> ByteReceiveStream | None:
        return self._stdout

    @property
    def stderr(self) -> ByteReceiveStream | None:
        return self._stderr


async def _spawn_process(
    command: StrOrBytesPath | Sequence[StrOrBytesPath],
    *,
    stdin: int | IO[Any] | None,
    stdout: int | IO[Any] | None,
    stderr: int | IO[Any] | None,
    **kwargs: Any,
) -> _Process:
    """
    Shared, backend-agnostic implementation of
    :meth:`~anyio.abc.AsyncBackend.open_process`.

    Standard streams requested as :data:`subprocess.PIPE` are connected to pipes created
    by the active backend; every other value is passed through to
    :class:`subprocess.Popen` unchanged.
    """
    backend = get_async_backend()
    await backend.checkpoint()
    if isinstance(command, PathLike):
        command = os.fspath(command)

    shell = isinstance(command, (str, bytes))
    stdin_stream: ByteSendStream | None = None
    stdout_stream: ByteReceiveStream | None = None
    stderr_stream: ByteReceiveStream | None = None
    streams: list[ByteSendStream | ByteReceiveStream] = []
    child_fds: list[int] = []
    try:
        if stdin == PIPE:
            stdin_stream, child_fd = await backend.create_subprocess_stdin_pipe()
            streams.append(stdin_stream)
            child_fds.append(child_fd)
            popen_stdin: Any = child_fd
        else:
            popen_stdin = stdin

        if stdout == PIPE:
            stdout_stream, child_fd = await backend.create_subprocess_output_pipe()
            streams.append(stdout_stream)
            child_fds.append(child_fd)
            popen_stdout: Any = child_fd
        else:
            popen_stdout = stdout

        if stderr == PIPE:
            stderr_stream, child_fd = await backend.create_subprocess_output_pipe()
            streams.append(stderr_stream)
            child_fds.append(child_fd)
            popen_stderr: Any = child_fd
        else:
            popen_stderr = stderr

        # Popen performs blocking reads on the exec-status pipe during startup, so it
        # must not run in the event loop thread.
        popen = await backend.run_sync_in_worker_thread(
            partial(
                subprocess.Popen,
                command,
                shell=shell,
                stdin=popen_stdin,
                stdout=popen_stdout,
                stderr=popen_stderr,
                **kwargs,
            ),
            (),
        )
    except BaseException:
        for stream in streams:
            await stream.aclose()

        raise
    finally:
        # The child now holds its own copies of these descriptors; close ours so that
        # EOF is delivered correctly once the child exits.
        for child_fd in child_fds:
            os.close(child_fd)

    return _Process(popen, stdin_stream, stdout_stream, stderr_stream)


async def run_process(
    command: StrOrBytesPath | Sequence[StrOrBytesPath],
    *,
    input: bytes | None = None,
    stdin: int | IO[Any] | None = None,
    stdout: int | IO[Any] | None = PIPE,
    stderr: int | IO[Any] | None = PIPE,
    check: bool = True,
    cwd: StrOrBytesPath | None = None,
    env: Mapping[str, str] | None = None,
    startupinfo: Any = None,
    creationflags: int = 0,
    start_new_session: bool = False,
    pass_fds: Sequence[int] = (),
    user: str | int | None = None,
    group: str | int | None = None,
    extra_groups: Iterable[str | int] | None = None,
    umask: int = -1,
) -> CompletedProcess[bytes]:
    """
    Run an external command in a subprocess and wait until it completes.

    .. seealso:: :func:`subprocess.run`

    :param command: either a string to pass to the shell, or an iterable of strings
        containing the executable name or path and its arguments
    :param input: bytes passed to the standard input of the subprocess
    :param stdin: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL`,
        a file-like object, or `None`; ``input`` overrides this
    :param stdout: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL`,
        a file-like object, or `None`
    :param stderr: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL`,
        :data:`subprocess.STDOUT`, a file-like object, or `None`
    :param check: if ``True``, raise :exc:`~subprocess.CalledProcessError` if the
        process terminates with a return code other than 0
    :param cwd: If not ``None``, change the working directory to this before running the
        command
    :param env: if not ``None``, this mapping replaces the inherited environment
        variables from the parent process
    :param startupinfo: an instance of :class:`subprocess.STARTUPINFO` that can be used
        to specify process startup parameters (Windows only)
    :param creationflags: flags that can be used to control the creation of the
        subprocess (see :class:`subprocess.Popen` for the specifics)
    :param start_new_session: if ``true`` the setsid() system call will be made in the
        child process prior to the execution of the subprocess. (POSIX only)
    :param pass_fds: sequence of file descriptors to keep open between the parent and
        child processes. (POSIX only)
    :param user: effective user to run the process as (Python >= 3.9, POSIX only)
    :param group: effective group to run the process as (Python >= 3.9, POSIX only)
    :param extra_groups: supplementary groups to set in the subprocess (Python >= 3.9,
        POSIX only)
    :param umask: if not negative, this umask is applied in the child process before
        running the given command (Python >= 3.9, POSIX only)
    :return: an object representing the completed process
    :raises ~subprocess.CalledProcessError: if ``check`` is ``True`` and the process
        exits with a nonzero return code

    """

    async def drain_stream(stream: AsyncIterable[bytes], index: int) -> None:
        buffer = BytesIO()
        async for chunk in stream:
            buffer.write(chunk)

        stream_contents[index] = buffer.getvalue()

    if stdin is not None and input is not None:
        raise ValueError("only one of stdin and input is allowed")

    async with await open_process(
        command,
        stdin=PIPE if input else stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        env=env,
        startupinfo=startupinfo,
        creationflags=creationflags,
        start_new_session=start_new_session,
        pass_fds=pass_fds,
        user=user,
        group=group,
        extra_groups=extra_groups,
        umask=umask,
    ) as process:
        stream_contents: list[bytes | None] = [None, None]
        async with create_task_group() as tg:
            if process.stdout:
                tg.start_soon(drain_stream, process.stdout, 0)

            if process.stderr:
                tg.start_soon(drain_stream, process.stderr, 1)

            if process.stdin and input:
                await process.stdin.send(input)
                await process.stdin.aclose()

            await process.wait()

    output, errors = stream_contents
    if check and process.returncode != 0:
        raise CalledProcessError(cast(int, process.returncode), command, output, errors)

    return CompletedProcess(command, cast(int, process.returncode), output, errors)


async def open_process(
    command: StrOrBytesPath | Sequence[StrOrBytesPath],
    *,
    stdin: int | IO[Any] | None = PIPE,
    stdout: int | IO[Any] | None = PIPE,
    stderr: int | IO[Any] | None = PIPE,
    cwd: StrOrBytesPath | None = None,
    env: Mapping[str, str] | None = None,
    startupinfo: Any = None,
    creationflags: int = 0,
    start_new_session: bool = False,
    pass_fds: Sequence[int] = (),
    user: str | int | None = None,
    group: str | int | None = None,
    extra_groups: Iterable[str | int] | None = None,
    umask: int = -1,
) -> Process:
    """
    Start an external command in a subprocess.

    .. seealso:: :class:`subprocess.Popen`

    :param command: either a string to pass to the shell, or an iterable of strings
        containing the executable name or path and its arguments
    :param stdin: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL`, a
        file-like object, or ``None``
    :param stdout: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL`,
        a file-like object, or ``None``
    :param stderr: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL`,
        :data:`subprocess.STDOUT`, a file-like object, or ``None``
    :param cwd: If not ``None``, the working directory is changed before executing
    :param env: If env is not ``None``, it must be a mapping that defines the
        environment variables for the new process
    :param creationflags: flags that can be used to control the creation of the
        subprocess (see :class:`subprocess.Popen` for the specifics)
    :param startupinfo: an instance of :class:`subprocess.STARTUPINFO` that can be used
        to specify process startup parameters (Windows only)
    :param start_new_session: if ``true`` the setsid() system call will be made in the
        child process prior to the execution of the subprocess. (POSIX only)
    :param pass_fds: sequence of file descriptors to keep open between the parent and
        child processes. (POSIX only)
    :param user: effective user to run the process as (POSIX only)
    :param group: effective group to run the process as (POSIX only)
    :param extra_groups: supplementary groups to set in the subprocess (POSIX only)
    :param umask: if not negative, this umask is applied in the child process before
        running the given command (POSIX only)
    :return: an asynchronous process object

    """
    kwargs: dict[str, Any] = {}
    if user is not None:
        kwargs["user"] = user

    if group is not None:
        kwargs["group"] = group

    if extra_groups is not None:
        kwargs["extra_groups"] = extra_groups

    if umask >= 0:
        kwargs["umask"] = umask

    return await get_async_backend().open_process(
        command,
        stdin=stdin,
        stdout=stdout,
        stderr=stderr,
        cwd=cwd,
        env=env,
        startupinfo=startupinfo,
        creationflags=creationflags,
        start_new_session=start_new_session,
        pass_fds=pass_fds,
        **kwargs,
    )
