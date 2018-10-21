import sys
from functools import partial
from typing import Callable, Set, List, Optional, Awaitable  # noqa: F401

import curio.io
import curio.socket
import curio.ssl
import curio.traps
from async_generator import async_generator, asynccontextmanager, yield_

from .._networking import BaseSocket
from .. import abc, T_Retval, claim_current_thread, _local
from ..exceptions import ExceptionGroup, CancelledError, ClosedResourceError


#
# Main entry point
#

def run(func: Callable[..., T_Retval], *args, **curio_options) -> T_Retval:
    async def wrapper():
        nonlocal exception, retval
        try:
            retval = await func(*args)
        except BaseException as exc:
            exception = exc

    exception = retval = None
    curio.run(wrapper, **curio_options)
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
        self._tasks = set()  # type: Set[curio.Task]
        self._cancel_called = False

    def add_task(self, task: curio.Task) -> None:
        self._tasks.add(task)

    def remove_task(self, task: curio.Task) -> None:
        self._tasks.remove(task)

    async def cancel(self):
        if not self._cancel_called:
            self._cancel_called = True

            for task in self._tasks:
                if task.coro.cr_await is not None:
                    await task.cancel(blocking=False)

            for scope in self.children:
                await scope.cancel()


def get_cancel_scope(task: curio.Task) -> Optional[CancelScope]:
    try:
        return _local.cancel_scopes_by_task.get(task)
    except AttributeError:
        return None


def set_cancel_scope(task: curio.Task, scope: Optional[CancelScope]) -> None:
    try:
        cancel_scopes = _local.cancel_scopes_by_task
    except AttributeError:
        cancel_scopes = _local.cancel_scopes_by_task = {}

    if scope is None:
        del cancel_scopes[task]
    else:
        cancel_scopes[task] = scope


async def check_cancelled():
    task = await curio.current_task()
    cancel_scope = get_cancel_scope(task)
    if cancel_scope is not None and cancel_scope._cancel_called:
        raise CancelledError


async def sleep(seconds: int):
    await check_cancelled()
    await curio.sleep(seconds)


@asynccontextmanager
@async_generator
async def open_cancel_scope():
    await check_cancelled()
    task = await curio.current_task()
    scope = CancelScope()
    scope.add_task(task)
    parent_scope = get_cancel_scope(task)
    if parent_scope is not None:
        parent_scope.children.add(scope)

    set_cancel_scope(task, scope)
    try:
        await yield_(scope)
    finally:
        if parent_scope is not None:
            parent_scope.children.remove(scope)
            set_cancel_scope(task, scope)
        else:
            set_cancel_scope(task, None)


@asynccontextmanager
@async_generator
async def fail_after(delay: float):
    async with open_cancel_scope() as cancel_scope:
        async with curio.ignore_after(delay) as s:
            await yield_()

        if s.expired:
            await cancel_scope.cancel()
            raise TimeoutError


@asynccontextmanager
@async_generator
async def move_on_after(delay: float):
    async with curio.ignore_after(delay):
        await yield_()


#
# Task groups
#

class TaskGroup:
    __slots__ = 'cancel_scope', '_active', '_tasks', '_host_task', '_exceptions'

    def __init__(self, cancel_scope: 'CancelScope', host_task: curio.Task) -> None:
        self.cancel_scope = cancel_scope
        self._host_task = host_task
        self._active = True
        self._exceptions = []  # type: List[BaseException]
        self._tasks = set()  # type: Set[curio.Task]

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        task = await curio.spawn(func, *args, report_crash=False)
        task._taskgroup = self
        self._tasks.add(task)
        if name is not None:
            task.name = name

        # Make the spawned task inherit the current cancel scope
        current_task = await curio.current_task()
        cancel_scope = get_cancel_scope(current_task)
        cancel_scope.add_task(task)
        set_cancel_scope(task, cancel_scope)

    async def _task_done(self, task: curio.Task) -> None:
        self._tasks.remove(task)

    def _task_discard(self, task: curio.Task) -> None:
        # Remove the task from its cancel scope
        cancel_scope = get_cancel_scope(task)  # type: CancelScope
        if cancel_scope is not None:
            cancel_scope.remove_task(task)

        self._tasks.discard(task)
        if task.terminated and task.exception is not None:
            if not isinstance(task.exception, (CancelledError, curio.TaskCancelled,
                                               curio.CancelledError)):
                self._exceptions.append(task.exception)


abc.TaskGroup.register(TaskGroup)


@asynccontextmanager
@async_generator
async def create_task_group():
    async with open_cancel_scope() as cancel_scope:
        current_task = await curio.current_task()
        group = TaskGroup(cancel_scope, current_task)
        try:
            await yield_(group)
        except (CancelledError, curio.CancelledError, curio.TaskCancelled):
            await cancel_scope.cancel()
        except BaseException as exc:
            group._exceptions.append(exc)
            await cancel_scope.cancel()

        while group._tasks:
            for task in set(group._tasks):
                await task.wait()

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
        asynclib = sys.modules[__name__]
        with claim_current_thread(asynclib):
            return func(*args)

    await check_cancelled()
    thread = await curio.spawn_thread(thread_worker)
    try:
        return await thread.join()
    except curio.TaskError as exc:
        raise exc.__cause__ from None


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    return curio.AWAIT(func(*args))


#
# Async file I/O
#

async def aopen(*args, **kwargs):
    fp = await run_in_thread(partial(open, *args, **kwargs))
    return curio.file.AsyncFile(fp)


#
# Networking
#

class Socket(BaseSocket):
    _reader_tasks = {}
    _writer_tasks = {}

    async def _wait_readable(self):
        task = await curio.current_task()
        self._reader_tasks[self._raw_socket] = task
        try:
            await curio.traps._read_wait(self._raw_socket)
        except curio.TaskCancelled:
            if self._raw_socket.fileno() == -1:
                raise ClosedResourceError from None
            else:
                raise
        finally:
            del self._reader_tasks[self._raw_socket]

    async def _wait_writable(self):
        task = await curio.current_task()
        self._writer_tasks[self._raw_socket] = task
        try:
            await curio.traps._write_wait(self._raw_socket)
        except curio.TaskCancelled:
            if self._raw_socket.fileno() == -1:
                raise ClosedResourceError from None
            else:
                raise
        finally:
            del self._writer_tasks[self._raw_socket]

    async def _notify_close(self) -> None:
        task = Socket._reader_tasks.get(self._raw_socket)
        if task:
            await task.cancel(blocking=False)

        task = Socket._writer_tasks.get(self._raw_socket)
        if task:
            await task.cancel(blocking=False)

    def _check_cancelled(self) -> Awaitable[None]:
        return check_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


def wait_socket_readable(sock):
    return curio.traps._read_wait(sock)


def wait_socket_writable(sock):
    return curio.traps._write_wait(sock)


#
# Synchronization
#

class Lock(curio.Lock):
    async def __aenter__(self):
        await check_cancelled()
        return await super().__aenter__()


class Condition(curio.Condition):
    async def __aenter__(self):
        await check_cancelled()
        return await super().__aenter__()

    async def wait(self):
        await check_cancelled()
        return await super().wait()


class Event(curio.Event):
    async def wait(self):
        await check_cancelled()
        return await super().wait()


class Semaphore(curio.Semaphore):
    async def __aenter__(self):
        await check_cancelled()
        return await super().__aenter__()


class Queue(curio.Queue):
    async def get(self):
        await check_cancelled()
        return await super().get()

    async def put(self, item):
        await check_cancelled()
        return await super().put(item)


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
    async with curio.SignalQueue(*signals) as queue:
        await yield_(queue)


#
# Testing and debugging
#

async def wait_all_tasks_blocked():
    import gc

    this_task = await curio.current_task()
    while True:
        for obj in gc.get_objects():
            if isinstance(obj, curio.Task) and obj.coro.cr_await is None:
                if not obj.terminated and obj is not this_task:
                    await curio.sleep(0)
                    break
        else:
            return
