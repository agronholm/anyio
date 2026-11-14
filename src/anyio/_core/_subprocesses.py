from __future__ import annotations

from collections.abc import (
    AsyncIterable,
    Awaitable,
    Callable,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import suppress
from io import BytesIO
from os import PathLike
from subprocess import PIPE, CalledProcessError, CompletedProcess
from typing import IO, Any, TypeAlias, cast

from ..abc import Process, TaskStatus  # noqa: TC001
from ._eventloop import get_async_backend
from ._tasks import TASK_STATUS_IGNORED, CancelScope, create_task_group

StrOrBytesPath: TypeAlias = str | bytes | PathLike[str] | PathLike[bytes]


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
    deliver_cancel: Callable[[Process], Awaitable[object]] | None = None,
    task_status: TaskStatus[Process] = TASK_STATUS_IGNORED,
) -> CompletedProcess[bytes]:
    """
    Run an external command in a subprocess and wait until it completes.

    When called through :meth:`~.abc.TaskGroup.start`, return the :class:`~.abc.Process`
    to the caller as soon as it has been spawned. The task continues to manage the
    process, collect its output and check its exit status. The process is always waited
    for before the task finishes, including when it is cancelled.

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
    :param deliver_cancel: an async callable used to stop the process on cancellation or
        an error while communicating with it; by default the process is killed
        immediately. The callable receives the process, runs shielded from external
        cancellation, and is cancelled when the process exits. If it raises an exception,
        the process is killed and the exception propagated. Output pipes continue to be
        drained while waiting for the process to exit.
    :param task_status: used with :meth:`~.abc.TaskGroup.start` to return the process to
        the caller; its standard output and error pipes are consumed by this function
        and must not be read by the caller
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

    process = await open_process(
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
    )
    try:

        async def cancel_process() -> None:
            assert deliver_cancel is not None
            try:
                await deliver_cancel(process)
            except BaseException:
                # A callback that raises cancellation must also stop the child:
                # task groups do not propagate cancellation raised by a child task.
                if process.returncode is None:
                    with suppress(ProcessLookupError):
                        process.kill()

                raise

        stream_contents: list[bytes | None] = [None, None]
        try:
            async with create_task_group() as tg:
                if process.stdout:
                    tg.start_soon(drain_stream, process.stdout, 0)

                if process.stderr:
                    tg.start_soon(drain_stream, process.stderr, 1)

                task_status.started(process)
                if process.stdin and input:
                    await process.stdin.send(input)
                    await process.stdin.aclose()

                await process.wait()
        except BaseException:
            with CancelScope(shield=True):
                try:
                    if deliver_cancel is not None:
                        async with create_task_group() as cancel_tg:
                            # The original readers have stopped. Keep draining so a
                            # child flushing output during shutdown cannot deadlock.
                            if process.stdout:
                                cancel_tg.start_soon(drain_stream, process.stdout, 0)

                            if process.stderr:
                                cancel_tg.start_soon(drain_stream, process.stderr, 1)

                            cancel_tg.start_soon(cancel_process)
                            await process.wait()
                            cancel_tg.cancel_scope.cancel()
                finally:
                    if process.returncode is None:
                        with suppress(ProcessLookupError):
                            process.kill()

                    await process.wait()

            raise
    finally:
        # In particular, do not let cancellation during aclose() replace an
        # exception raised by the cancellation callback.
        with CancelScope(shield=True):
            await process.aclose()

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
