from subprocess import DEVNULL, PIPE, CalledProcessError, CompletedProcess
from typing import Optional, Sequence, Union, cast

from ..abc import Process
from ._eventloop import get_asynclib
from ._tasks import create_task_group


async def run_process(command: Union[str, Sequence[str]], *, input: Optional[bytes] = None,
                      stdout: int = PIPE, stderr: int = PIPE,
                      check: bool = True) -> CompletedProcess:
    """
    Run an external command in a subprocess and wait until it completes.

    .. seealso:: :func:`subprocess.run`

    :param command: either a string to pass to the shell, or an iterable of strings containing the
        executable name or path and its arguments
    :param input: bytes passed to the standard input of the subprocess
    :param stdout: either :data:`subprocess.PIPE` or :data:`subprocess.DEVNULL`
    :param stderr: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL` or
        :data:`subprocess.STDOUT`
    :param check: if ``True``, raise :exc:`~subprocess.CalledProcessError` if the process
        terminates with a return code other than 0
    :return: an object representing the completed process
    :raises ~subprocess.CalledProcessError: if ``check`` is ``True`` and the process exits with a
        nonzero return code

    """
    async def drain_stream(stream, index):
        chunks = [chunk async for chunk in stream]
        stream_contents[index] = b''.join(chunks)

    async with await open_process(command, stdin=PIPE if input else DEVNULL, stdout=stdout,
                                  stderr=stderr) as process:
        stream_contents = [None, None]
        try:
            async with create_task_group() as tg:
                if process.stdout:
                    await tg.spawn(drain_stream, process.stdout, 0)
                if process.stderr:
                    await tg.spawn(drain_stream, process.stderr, 1)
                if process.stdin and input:
                    await process.stdin.send(input)
                    await process.stdin.aclose()

                await process.wait()
        except BaseException:
            process.kill()
            raise

    output, errors = stream_contents
    if check and process.returncode != 0:
        raise CalledProcessError(cast(int, process.returncode), command, output, errors)

    return CompletedProcess(command, cast(int, process.returncode), output, errors)


async def open_process(command: Union[str, Sequence[str]], *, stdin: int = PIPE,
                       stdout: int = PIPE, stderr: int = PIPE) -> Process:
    """
    Start an external command in a subprocess.

    .. seealso:: :class:`subprocess.Popen`

    :param command: either a string to pass to the shell, or an iterable of strings containing the
        executable name or path and its arguments
    :param stdin: either :data:`subprocess.PIPE` or :data:`subprocess.DEVNULL`
    :param stdout: either :data:`subprocess.PIPE` or :data:`subprocess.DEVNULL`
    :param stderr: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL` or
        :data:`subprocess.STDOUT`
    :return: an asynchronous process object

    """
    shell = isinstance(command, str)
    return await get_asynclib().open_process(command, shell=shell, stdin=stdin, stdout=stdout,
                                             stderr=stderr)
