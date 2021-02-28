import os
import platform
import threading
import traceback
from collections import deque
from itertools import count
from multiprocessing import get_context
from threading import BrokenBarrierError
from typing import Callable, Optional, TypeVar

from ..abc import CapacityLimiter
from ._eventloop import get_asynclib
from ._lowlevel import checkpoint
from ._synchronization import create_capacity_limiter
from ._tasks import create_task_group, open_cancel_scope
from ._threads import run_sync_in_worker_thread

T_Retval = TypeVar('T_Retval')


# Code to embed a traceback in a remote exception.  This is borrowed
# straight from multiprocessing.pool.  Copied here to avoid possible
# confusion when reading the traceback message (it will identify itself
# as originating from curio as opposed to multiprocessing.pool).

class RemoteTraceback(Exception):

    def __init__(self, tb):
        self.tb = tb

    def __str__(self):
        return self.tb


class ExceptionWithTraceback:

    def __init__(self, exc, tb):
        tb = traceback.format_exception(type(exc), exc, tb)
        tb = ''.join(tb)
        self.exc = exc
        self.tb = '\n"""\n%s"""' % tb

    def __reduce__(self):
        return rebuild_exc, (self.exc, self.tb)


def rebuild_exc(exc, tb):
    exc.__cause__ = RemoteTraceback(tb)
    return exc


class BrokenWorkerError(RuntimeError):
    """Raised when a worker process fails or dies unexpectedly.

    This error is not typically encountered in normal use, and indicates a severe
    failure of either anyio or the code that was executing in the worker.
    """

    pass


DEFAULT_LIMIT = os.cpu_count() or 2
_limiter_local = threading.local()
_limiter_local.limiters = {}


def current_default_worker_process_limiter() -> CapacityLimiter:
    """
    Return the capacity limiter that is used by default to limit the number of concurrent
    processes. Defaults to the value returned by os.cpu_count()

    :return: a capacity limiter object

    """

    try:
        return _limiter_local.limiters[get_asynclib()]
    except KeyError:
        limiter = _limiter_local.limiters[get_asynclib()] = create_capacity_limiter(DEFAULT_LIMIT)
        return limiter


# How long a process will idle waiting for new work before gives up and exits.
# This should be longer than a thread timeout proportionately to startup time.
IDLE_TIMEOUT = 60 * 10

_proc_counter = count()


class WorkerProc:
    def __init__(self, mp_context=get_context("spawn")):
        # It is almost possible to synchronize on the pipe alone but on Pypy
        # the _send_pipe doesn't raise the correct error on death. Anyway,
        # this Barrier strategy is more obvious to understand.
        self._barrier = mp_context.Barrier(2)
        child_recv_pipe, self._send_pipe = mp_context.Pipe(duplex=False)
        self._recv_pipe, child_send_pipe = mp_context.Pipe(duplex=False)
        self._proc = mp_context.Process(
            target=self._work,
            args=(self._barrier, child_recv_pipe, child_send_pipe),
            name=f"trio-parallel worker process {next(_proc_counter)}",
            daemon=True,
        )
        # keep our own state flag for quick checks
        self._started = False

    @staticmethod
    def _work(barrier, recv_pipe, send_pipe):  # pragma: no cover

        import inspect

        def coroutine_checker(fn, args):
            ret = fn(*args)
            if inspect.iscoroutine(ret):
                # Manually close coroutine to avoid RuntimeWarnings
                ret.close()
                raise TypeError(
                    "Worker expected a sync function, but {!r} appears "
                    "to be asynchronous".format(getattr(fn, "__qualname__", fn))
                )

            return ret

        while True:
            try:
                # Return value is party #, not whether awoken within timeout
                barrier.wait(timeout=IDLE_TIMEOUT)
            except BrokenBarrierError:
                # Timeout waiting for job, so we can exit.
                return
            # We got a job, and we are "woken"
            fn, args = recv_pipe.recv()
            # Send the result to the main process and go back to idling
            try:
                result = coroutine_checker(fn, args)
            except BaseException as err:
                send_pipe.send((ExceptionWithTraceback(err, err.__traceback__), True))
            else:
                send_pipe.send((result, False))

            del fn
            del args
            del result

    def _communicate_job(self, sync_fn, args):
        self._send_pipe.send((sync_fn, args))
        return self._recv_pipe.recv()

    async def run_sync(self, sync_fn, *args):
        # Neither this nor the child process should be waiting at this point
        assert not self._barrier.n_waiting, "Must first wake_up() the worker"
        try:
            # NOTE: upon cancellation the worker must be killed to free the thread
            outcome, error = await run_sync_in_worker_thread(
                self._communicate_job, sync_fn, args, cancellable=True)
        except EOFError:
            # Likely the worker died while we were waiting on a pipe
            self.kill()  # NOTE: must reap zombie child elsewhere
            raise BrokenWorkerError(f"{self._proc} died unexpectedly")
        except BaseException:
            # Cancellation or other unknown errors leave the process in an
            # unknown state, so there is no choice but to kill.
            self.kill()  # NOTE: must reap zombie child elsewhere
            raise
        else:
            if error:
                raise outcome
            else:
                return outcome

    def is_alive(self):
        # if the proc is alive, there is a race condition where it could be
        # dying, but the the barrier should be broken at that time. This
        # call reaps zombie children on Unix.
        return self._proc.is_alive()

    def wake_up(self, timeout=None):
        if not self._started:
            self._proc.start()
            self._started = True
        try:
            self._barrier.wait(timeout)
        except BrokenBarrierError:
            # raise our own flavor of exception and reap child
            if self._proc.is_alive():  # pragma: no cover - rare race condition
                self.kill()
                self._proc.join(1)  # this will block for ms, but it should be rare
                assert not self._proc.is_alive(), f"{self._proc} alive after failed wakeup"
            raise BrokenWorkerError(f"{self._proc} died unexpectedly") from None

    def kill(self):
        # race condition: if we kill while the proc has the underlying
        # semaphore, we can deadlock it, so make sure we hold it.
        with self._barrier._cond:
            self._barrier.abort()
            try:
                self._proc.kill()
            except AttributeError:
                # cpython 3.6 has an edge case where if this process holds
                # the semaphore, a wait can timeout and raise an OSError.
                self._proc.terminate()

    async def wait(self):
        while self._proc.is_alive():
            await run_sync_in_worker_thread(self._proc.join, 1, cancellable=True)


class PypyWorkerProc(WorkerProc):
    async def run_sync(self, sync_fn, *args):
        async with create_task_group() as group:
            group.spawn(self.child_monitor)
            result = await super().run_sync(sync_fn, *args)
            group.cancel_scope.cancel()
        return result

    async def child_monitor(self):
        # If this worker dies, raise a catchable error...
        await self.wait()
        # but not if another error or cancel is incoming, those take priority!
        await checkpoint()
        raise BrokenWorkerError(f"{self._proc} died unexpectedly")


class WorkerCache:
    def __init__(self):
        # The cache is a deque rather than dict here since processes can't remove
        # themselves anyways, so we don't need O(1) lookups
        self._cache = deque()
        # NOTE: avoid thread races between runs by only interacting with
        # self._cache via thread-atomic actions like append, pop, del

    def prune(self):
        # take advantage of the oldest proc being on the left to
        # keep iteration O(dead workers)
        try:
            while True:
                proc = self._cache.popleft()
                if proc.is_alive():
                    self._cache.appendleft(proc)
                    return
        except IndexError:
            # Thread safety: it's necessary to end the iteration using this error
            # when the cache is empty, as opposed to `while self._cache`.
            pass

    def push(self, proc):
        self._cache.append(proc)

    def pop(self):
        # Get live, WOKEN worker process or raise IndexError
        while True:
            proc = self._cache.pop()
            try:
                proc.wake_up(0)
            except BrokenWorkerError:
                # proc must have died in the cache, just try again
                continue
            else:
                return proc

    def __len__(self):
        return len(self._cache)


WORKER_CACHE = WorkerCache()


async def run_sync_in_worker_process(
        func: Callable[..., T_Retval], *args, cancellable: bool = False,
        limiter: Optional[CapacityLimiter] = None) -> T_Retval:
    """
    Call the given function with the given arguments in a worker processs.

    If the ``cancellable`` option is enabled and the task waiting for its completion is cancelled,
    the process will be terminated with SIGKILL/TerminateProcess.

    :param func: a callable
    :param args: positional arguments for the callable
    :param cancellable: ``True`` to allow cancellation of the operation
    :param limiter: capacity limiter to use to limit the total amount of processes running
        (if omitted, the default limiter is used)
    :return: an awaitable that yields the return value of the function.

    """

    if limiter is None:
        limiter = current_default_worker_process_limiter()

    async with limiter:
        await checkpoint()
        WORKER_CACHE.prune()

        try:
            proc = WORKER_CACHE.pop()
        except IndexError:
            if platform.python_implementation() == "PyPy":
                proc = PypyWorkerProc()
            else:
                proc = WorkerProc()
            await run_sync_in_worker_thread(proc.wake_up)

        try:
            with open_cancel_scope(shield=not cancellable):
                return await proc.run_sync(func, *args)
        finally:
            if proc.is_alive():
                WORKER_CACHE.push(proc)
