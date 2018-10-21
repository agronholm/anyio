import asyncio
import inspect
import os
import socket
import sys
from contextlib import suppress
from functools import partial
from threading import Thread
from typing import Callable, Set, Optional, List, Union  # noqa: F401

from async_generator import async_generator, yield_, asynccontextmanager

from .._networking import BaseSocket
from .. import abc, claim_current_thread, _local, T_Retval
from ..exceptions import ExceptionGroup, CancelledError, ClosedResourceError

try:
    from asyncio import run as native_run, create_task, get_running_loop, current_task, all_tasks
except ImportError:
    # Snatched from the standard library
    def native_run(main, *, debug=False):
        """Run a coroutine.

        This function runs the passed coroutine, taking care of
        managing the asyncio event loop and finalizing asynchronous
        generators.

        This function cannot be called when another asyncio event loop is
        running in the same thread.

        If debug is True, the event loop will be run in debug mode.

        This function always creates a new event loop and closes it at the end.
        It should be used as a main entry point for asyncio programs, and should
        ideally only be called once.

        Example:

            async def main():
                await asyncio.sleep(1)
                print('hello')

            asyncio.run(main())
        """
        from asyncio import events, coroutines

        if events._get_running_loop() is not None:
            raise RuntimeError(
                "asyncio.run() cannot be called from a running event loop")

        if not coroutines.iscoroutine(main):
            raise ValueError("a coroutine was expected, got {!r}".format(main))

        loop = events.new_event_loop()
        try:
            events.set_event_loop(loop)
            loop.set_debug(debug)
            return loop.run_until_complete(main)
        finally:
            try:
                _cancel_all_tasks(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                events.set_event_loop(None)
                loop.close()

    def _cancel_all_tasks(loop):
        from asyncio import Task, gather

        to_cancel = Task.all_tasks(loop)
        if not to_cancel:
            return

        for task in to_cancel:
            task.cancel()

        loop.run_until_complete(
            gather(*to_cancel, loop=loop, return_exceptions=True))

        for task in to_cancel:
            if task.cancelled():
                continue
            if task.exception() is not None:
                loop.call_exception_handler({
                    'message': 'unhandled exception during asyncio.run() shutdown',
                    'exception': task.exception(),
                    'task': task,
                })

    def create_task(coro) -> asyncio.Task:
        return get_running_loop().create_task(coro)

    def get_running_loop():
        loop = asyncio._get_running_loop()
        if loop is not None:
            return loop
        else:
            raise RuntimeError('no running event loop')

    current_task = asyncio.Task.current_task
    all_tasks = asyncio.Task.all_tasks

_create_task_supports_name = 'name' in inspect.signature(create_task).parameters


#
# Main entry point
#

def run(func: Callable[..., T_Retval], *args, debug: bool = False,
        policy: Optional[asyncio.AbstractEventLoopPolicy] = None) -> T_Retval:
    async def wrapper():
        nonlocal exception, retval
        try:
            retval = await func(*args)
        except BaseException as exc:
            exception = exc

    if policy is not None:
        asyncio.set_event_loop_policy(policy)

    exception = retval = None
    native_run(wrapper(), debug=debug)
    if exception is not None:
        raise exception
    else:
        return retval


#
# Timeouts and cancellation
#

class CancelScope(abc.CancelScope):
    __slots__ = 'children', '_tasks', '_cancel_called'

    def __init__(self) -> None:
        self.children = set()  # type: Set[CancelScope]
        self._tasks = set()  # type: Set[asyncio.Task]
        self._cancel_called = False

    def add_task(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        set_cancel_scope(task, self)
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.remove(task)
        set_cancel_scope(task, None)

    async def cancel(self):
        if not self._cancel_called:
            self._cancel_called = True

            # Cancel all tasks that have started (i.e. they're awaiting on something)
            for task in self._tasks:
                coro = task._coro  # dirty, but works with both the stdlib event loop and uvloop
                if coro.cr_await is not None:
                    task.cancel()

            for child in self.children:
                await child.cancel()


def get_cancel_scope(task: asyncio.Task) -> Optional[CancelScope]:
    try:
        return _local.cancel_scopes_by_task.get(task)
    except AttributeError:
        return None


def set_cancel_scope(task: asyncio.Task, scope: Optional[CancelScope]):
    try:
        cancel_scopes = _local.cancel_scopes_by_task
    except AttributeError:
        cancel_scopes = _local.cancel_scopes_by_task = {}

    if scope is None:
        del cancel_scopes[task]
    else:
        cancel_scopes[task] = scope


def check_cancelled():
    task = current_task()
    cancel_scope = get_cancel_scope(task)
    if cancel_scope is not None and cancel_scope._cancel_called:
        raise CancelledError


async def sleep(delay: float) -> None:
    check_cancelled()
    await asyncio.sleep(delay)


@asynccontextmanager
@async_generator
async def open_cancel_scope():
    task = current_task()
    scope = CancelScope()
    scope.add_task(task)
    parent_scope = get_cancel_scope(task)
    if parent_scope is not None:
        parent_scope.children.add(scope)

    try:
        await yield_(scope)
    finally:
        if parent_scope is not None:
            parent_scope.children.remove(scope)
            set_cancel_scope(task, parent_scope)
        else:
            set_cancel_scope(task, None)


@asynccontextmanager
@async_generator
async def fail_after(delay: float):
    async def timeout():
        nonlocal timeout_expired
        await sleep(delay)
        timeout_expired = True
        await scope.cancel()

    timeout_expired = False
    async with open_cancel_scope() as scope:
        timeout_task = get_running_loop().create_task(timeout())
        try:
            await yield_(scope)
        except asyncio.CancelledError as exc:
            if timeout_expired:
                await scope.cancel()
                raise TimeoutError().with_traceback(exc.__traceback__) from None
            else:
                raise
        finally:
            timeout_task.cancel()
            await asyncio.gather(timeout_task, return_exceptions=True)


@asynccontextmanager
@async_generator
async def move_on_after(delay: float):
    async def timeout():
        nonlocal timeout_expired
        await sleep(delay)
        timeout_expired = True
        await scope.cancel()

    timeout_expired = False
    async with open_cancel_scope() as scope:
        timeout_task = get_running_loop().create_task(timeout())
        try:
            await yield_(scope)
        except asyncio.CancelledError:
            if timeout_expired:
                await scope.cancel()
            else:
                raise
        finally:
            timeout_task.cancel()
            await asyncio.gather(timeout_task, return_exceptions=True)


#
# Task groups
#

class TaskGroup:
    __slots__ = 'cancel_scope', '_active', '_tasks', '_host_task', '_exceptions'

    def __init__(self, cancel_scope: 'CancelScope', host_task: asyncio.Task) -> None:
        self.cancel_scope = cancel_scope
        self._host_task = host_task
        self._active = True
        self._exceptions = []  # type: List[BaseException]
        self._tasks = set()  # type: Set[asyncio.Task]

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.remove(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None and not isinstance(exc, CancelledError):
                self._exceptions.append(exc)
                self._host_task.cancel()

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        if _create_task_supports_name:
            task = create_task(func(*args), name=name)
        else:
            task = create_task(func(*args))

        self._tasks.add(task)
        task.add_done_callback(self._task_done)

        # Make the spawned task inherit the task group's cancel scope
        set_cancel_scope(task, self.cancel_scope)
        self.cancel_scope.add_task(task)


abc.TaskGroup.register(TaskGroup)


@asynccontextmanager
@async_generator
async def create_task_group():
    async with open_cancel_scope() as cancel_scope:
        group = TaskGroup(cancel_scope, current_task())
        try:
            await yield_(group)
        except CancelledError:
            await cancel_scope.cancel()
        except BaseException as exc:
            group._exceptions.append(exc)
            await cancel_scope.cancel()

        while group._tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.wait(group._tasks)

        group._active = False
        if len(group._exceptions) > 1:
            raise ExceptionGroup(group._exceptions)
        elif group._exceptions:
            raise group._exceptions[0]


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    def thread_worker():
        try:
            with claim_current_thread(asynclib):
                _local.loop = loop
                result = func(*args)
        except BaseException as exc:
            loop.call_soon_threadsafe(queue.put_nowait, (None, exc))
        else:
            loop.call_soon_threadsafe(queue.put_nowait, (result, None))

    check_cancelled()
    asynclib = sys.modules[__name__]
    loop = get_running_loop()
    queue = asyncio.Queue(1)
    thread = Thread(target=thread_worker)
    thread.start()
    retval, exception = await queue.get()
    if exception is not None:
        raise exception
    else:
        return retval


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    f = asyncio.run_coroutine_threadsafe(func(*args), _local.loop)
    return f.result()


#
# Async file I/O
#

class AsyncFile:
    def __init__(self, fp) -> None:
        self._fp = fp

    def __getattr__(self, name):
        return getattr(self._fp, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.close()

    @async_generator
    async def __aiter__(self):
        while True:
            line = await self.readline()
            if line:
                await yield_(line)
            else:
                break

    async def read(self, size: int = -1) -> Union[bytes, str]:
        return await run_in_thread(self._fp.read, size)

    async def read1(self, size: int = -1) -> Union[bytes, str]:
        return await run_in_thread(self._fp.read1, size)

    async def readline(self) -> bytes:
        return await run_in_thread(self._fp.readline)

    async def readlines(self) -> bytes:
        return await run_in_thread(self._fp.readlines)

    async def readinto(self, b: Union[bytes, memoryview]) -> bytes:
        return await run_in_thread(self._fp.readinto, b)

    async def readinto1(self, b: Union[bytes, memoryview]) -> bytes:
        return await run_in_thread(self._fp.readinto1, b)

    async def write(self, b: bytes) -> None:
        return await run_in_thread(self._fp.write, b)

    async def writelines(self, lines: bytes) -> None:
        return await run_in_thread(self._fp.writelines, lines)

    async def truncate(self, size: Optional[int] = None) -> int:
        return await run_in_thread(self._fp.truncate, size)

    async def seek(self, offset: int, whence: Optional[int] = os.SEEK_SET) -> int:
        return await run_in_thread(self._fp.seek, offset, whence)

    async def tell(self) -> int:
        return await run_in_thread(self._fp.tell)

    async def flush(self) -> None:
        return await run_in_thread(self._fp.flush)

    async def close(self) -> None:
        return await run_in_thread(self._fp.close)


async def aopen(*args, **kwargs):
    fp = await run_in_thread(partial(open, *args, **kwargs))
    return AsyncFile(fp)


#
# Networking
#


class Socket(BaseSocket):
    __slots__ = '_loop', '_read_event', '_write_event'

    def __init__(self, raw_socket: socket.SocketType) -> None:
        self._loop = get_running_loop()
        self._read_event = asyncio.Event(loop=self._loop)
        self._write_event = asyncio.Event(loop=self._loop)
        super().__init__(raw_socket)

    async def _wait_readable(self) -> None:
        check_cancelled()
        self._loop.add_reader(self._raw_socket, self._read_event.set)
        try:
            await self._read_event.wait()
            self._read_event.clear()
        finally:
            self._loop.remove_reader(self._raw_socket)

        if self._raw_socket.fileno() == -1:
            raise ClosedResourceError

    async def _wait_writable(self) -> None:
        check_cancelled()
        self._loop.add_writer(self._raw_socket, self._write_event.set)
        try:
            await self._write_event.wait()
            self._write_event.clear()
        finally:
            self._loop.remove_writer(self._raw_socket)

        if self._raw_socket.fileno() == -1:
            raise ClosedResourceError

    async def _notify_close(self) -> None:
        self._read_event.set()
        self._write_event.set()

    async def _check_cancelled(self) -> None:
        check_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


async def wait_socket_readable(sock: socket.SocketType) -> None:
    check_cancelled()
    loop = get_running_loop()
    event = asyncio.Event(loop=loop)
    loop.add_reader(sock, event.set)
    try:
        await event.wait()
    finally:
        loop.remove_reader(sock)


async def wait_socket_writable(sock: socket.SocketType) -> None:
    check_cancelled()
    loop = get_running_loop()
    event = asyncio.Event(loop=loop)
    loop.add_writer(sock.fileno(), event.set)
    try:
        await event.wait()
    finally:
        loop.remove_writer(sock)


#
# Synchronization
#

class Lock(asyncio.Lock):
    async def __aenter__(self):
        check_cancelled()
        await self.acquire()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


class Condition(asyncio.Condition):
    async def __aenter__(self):
        check_cancelled()
        return await super().__aenter__()

    async def notify(self, n=1):
        super().notify(n)

    async def notify_all(self):
        super().notify(len(self._waiters))

    def wait(self):
        check_cancelled()
        return super().wait()


class Event(asyncio.Event):
    async def set(self):
        super().set()

    def wait(self):
        check_cancelled()
        return super().wait()


class Semaphore(asyncio.Semaphore):
    def __aenter__(self):
        check_cancelled()
        return super().__aenter__()

    @property
    def value(self):
        return self._value


class Queue(asyncio.Queue):
    def get(self):
        check_cancelled()
        return super().get()

    def put(self, item):
        check_cancelled()
        return super().put(item)


abc.Lock.register(Lock)
abc.Condition.register(Condition)
abc.Event.register(Event)
abc.Semaphore.register(Semaphore)
abc.Queue.register(Queue)


#
# Signal handling
#

@asynccontextmanager
@async_generator
async def receive_signals(*signals: int):
    @async_generator
    async def process_signal_queue():
        while True:
            signum = await queue.get()
            await yield_(signum)

    loop = get_running_loop()
    queue = asyncio.Queue(loop=loop)
    handled_signals = set()
    try:
        for sig in set(signals):
            loop.add_signal_handler(sig, queue.put_nowait, sig)
            handled_signals.add(sig)

        await yield_(process_signal_queue())
    finally:
        for sig in handled_signals:
            loop.remove_signal_handler(sig)


#
# Testing and debugging
#

async def wait_all_tasks_blocked():
    this_task = current_task()
    while True:
        for task in all_tasks():
            if task._coro.cr_await is None and task is not this_task:
                await sleep(0)
                break
        else:
            return
