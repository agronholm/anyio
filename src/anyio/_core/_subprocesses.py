import os
import pickle
import subprocess
import sys
from collections import deque
from subprocess import DEVNULL, PIPE, CalledProcessError, CompletedProcess
from typing import Callable, Deque, List, Optional, Sequence, Set, Tuple, TypeVar, Union, cast

from ..abc import ByteReceiveStream, ByteSendStream, Process
from ..lowlevel import RunVar, checkpoint_if_cancelled
from ..streams.buffered import BufferedByteReceiveStream
from ._eventloop import current_time, get_asynclib, get_cancelled_exc_class
from ._exceptions import BrokenWorkerProcess
from ._synchronization import CapacityLimiter
from ._tasks import CancelScope, create_task_group, fail_after

T_Retval = TypeVar('T_Retval')
_process_pool_workers: RunVar[Set[Process]] = RunVar('_process_pool_workers')
_process_pool_idle_workers: RunVar[Deque[Tuple[Process, float]]] = RunVar(
    '_process_pool_idle_workers')
_default_process_limiter: RunVar[CapacityLimiter] = RunVar('_default_process_limiter')

WORKER_MAX_IDLE_TIME = 300  # 5 minutes


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
                    tg.spawn(drain_stream, process.stdout, 0)
                if process.stderr:
                    tg.spawn(drain_stream, process.stderr, 1)
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


async def run_sync_in_process(
        func: Callable[..., T_Retval], *args, cancellable: bool = False,
        limiter: Optional[CapacityLimiter] = None) -> T_Retval:
    """
    Call the given function with the given arguments in a worker process.

    If the ``cancellable`` option is enabled and the task waiting for its completion is cancelled,
    the worker process running it will be abruptly terminated using SIGKILL (or
    ``terminateProcess()`` on Windows).

    :param func: a callable
    :param args: positional arguments for the callable
    :param cancellable: ``True`` to allow cancellation of the operation while it's running
    :param limiter: capacity limiter to use to limit the total amount of processes running
        (if omitted, the default limiter is used)
    :return: an awaitable that yields the return value of the function.

    """
    async def send_raw_command(pickled_cmd: bytes):
        try:
            await stdin.send(pickled_cmd)
            response = await buffered.receive_until(b'\n', 50)
            status, length = response.split(b' ')
            if status not in (b'RETURN', b'EXCEPTION'):
                raise RuntimeError(f'Worker process returned unexpected response: {response!r}')

            pickled_response = await buffered.receive_exactly(int(length))
        except BaseException as exc:
            workers.discard(process)
            try:
                process.kill()
                with CancelScope(shield=True):
                    await process.aclose()
            except ProcessLookupError:
                pass

            if isinstance(exc, get_cancelled_exc_class()):
                raise
            else:
                raise BrokenWorkerProcess from exc

        retval = pickle.loads(pickled_response)
        if status == b'EXCEPTION':
            assert isinstance(retval, BaseException)
            raise retval
        else:
            return retval

    # First pickle the request before trying to reserve a worker process
    await checkpoint_if_cancelled()
    request = pickle.dumps(('run', func, args), protocol=pickle.HIGHEST_PROTOCOL)

    # If this is the first run in this event loop thread, set up the necessary variables
    try:
        workers = _process_pool_workers.get()
        idle_workers = _process_pool_idle_workers.get()
    except LookupError:
        workers = set()
        idle_workers = deque()
        _process_pool_workers.set(workers)
        _process_pool_idle_workers.set(idle_workers)
        get_asynclib().setup_process_pool_exit_at_shutdown(workers)

    async with (limiter or current_default_worker_process_limiter()):
        # Pop processes from the pool (starting from the most recently used) until we find one that
        # hasn't exited yet
        process: Process
        while idle_workers:
            process, idle_since = idle_workers.pop()
            if process.returncode is None:
                stdin = cast(ByteSendStream, process.stdin)
                buffered = BufferedByteReceiveStream(cast(ByteReceiveStream, process.stdout))

                # Prune any other workers that have been idle for WORKER_MAX_IDLE_TIME seconds or
                # longer
                now = current_time()
                killed_processes: List[Process] = []
                while idle_workers:
                    if now - idle_workers[0][1] < WORKER_MAX_IDLE_TIME:
                        break

                    process, idle_since = idle_workers.popleft()
                    process.kill()
                    workers.remove(process)
                    killed_processes.append(process)

                with CancelScope(shield=True):
                    for process in killed_processes:
                        await process.aclose()

                break

            workers.remove(process)
        else:
            command = [sys.executable, '-u', '-m', 'anyio._core._subprocess_worker']
            process = await open_process(command, stdin=subprocess.PIPE,
                                         stdout=subprocess.PIPE)
            try:
                stdin = cast(ByteSendStream, process.stdin)
                buffered = BufferedByteReceiveStream(cast(ByteReceiveStream, process.stdout))
                with fail_after(20):
                    message = await buffered.receive(6)

                if message != b'READY\n':
                    raise BrokenWorkerProcess(
                        f'Worker process returned unexpected response: {message!r}')

                main_module_path = getattr(sys.modules['__main__'], '__file__', None)
                pickled = pickle.dumps(('init', sys.path, main_module_path),
                                       protocol=pickle.HIGHEST_PROTOCOL)
                await send_raw_command(pickled)
            except (BrokenWorkerProcess, get_cancelled_exc_class()):
                raise
            except BaseException as exc:
                process.kill()
                raise BrokenWorkerProcess('Error during worker process initialization') from exc

            workers.add(process)

        with CancelScope(shield=not cancellable):
            try:
                return await send_raw_command(request)
            finally:
                if process in workers:
                    idle_workers.append((process, current_time()))


def current_default_worker_process_limiter() -> CapacityLimiter:
    """
    Return the capacity limiter that is used by default to limit the number of worker processes.

    :return: a capacity limiter object

    """
    try:
        return _default_process_limiter.get()
    except LookupError:
        limiter = CapacityLimiter(os.cpu_count() or 2)
        _default_process_limiter.set(limiter)
        return limiter
