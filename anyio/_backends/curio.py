import sys
from contextlib import contextmanager
from functools import partial
from typing import Callable, Set, List, Optional, Awaitable  # noqa: F401

import curio.io
import curio.socket
import curio.ssl
import curio.traps
from async_generator import async_generator, asynccontextmanager, yield_

from .._networking import BaseSocket
from .. import abc, T_Retval, claim_current_thread, _local
from ..exceptions import ExceptionGroup, CancelledError


def run(func: Callable[..., T_Retval], *args) -> T_Retval:
    kernel = None
    try:
        with curio.Kernel() as kernel:
            return kernel.run(func, *args)
    except BaseException:
        if kernel:
            kernel.run(shutdown=True)

        raise


@contextmanager
def translate_exceptions():
    try:
        yield
    except (curio.CancelledError, curio.TaskCancelled) as exc:
        raise CancelledError().with_traceback(exc.__traceback__) from None


#
# Timeouts and cancellation
#

class CurioCancelScope(abc.CancelScope):
    __slots__ = 'children', '_tasks', '_cancel_called'

    def __init__(self) -> None:
        self.children = set()  # type: Set[CurioCancelScope]
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


def get_cancel_scope(task: curio.Task) -> Optional[CurioCancelScope]:
    try:
        return _local.cancel_scopes_by_task.get(task)
    except AttributeError:
        return None


def set_cancel_scope(task: curio.Task, scope: Optional[CurioCancelScope]) -> None:
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
    scope = CurioCancelScope()
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

class CurioTaskGroup:
    __slots__ = 'cancel_scope', '_active', '_tasks', '_host_task', '_exceptions'

    def __init__(self, cancel_scope: 'CurioCancelScope', host_task: curio.Task) -> None:
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
        cancel_scope = get_cancel_scope(task)  # type: CurioCancelScope
        if cancel_scope is not None:
            cancel_scope.remove_task(task)

        self._tasks.discard(task)
        if task.terminated and task.exception is not None:
            if not isinstance(task.exception, (CancelledError, curio.TaskCancelled,
                                               curio.CancelledError)):
                self._exceptions.append(task.exception)


@asynccontextmanager
@async_generator
async def create_task_group():
    async with open_cancel_scope() as cancel_scope:
        current_task = await curio.current_task()
        group = CurioTaskGroup(cancel_scope, current_task)
        try:
            with translate_exceptions():
                await yield_(group)
        except CancelledError:
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
    def wrapper():
        asynclib = sys.modules[__name__]
        with claim_current_thread(asynclib):
            return func(*args)

    await check_cancelled()
    thread = await curio.spawn_thread(wrapper)
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
    def _wait_readable(self) -> None:
        return wait_socket_readable(self._raw_socket)

    def _wait_writable(self) -> None:
        return wait_socket_writable(self._raw_socket)

    def _check_cancelled(self) -> Awaitable[None]:
        return check_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


def wait_socket_readable(sock):
    return curio.traps._read_wait(sock)


def wait_socket_writable(sock):
    return curio.traps._write_wait(sock)


#
# Signal handling
#

@asynccontextmanager
@async_generator
async def receive_signals(*signals: int):
    async with curio.SignalQueue(*signals) as queue:
        await yield_(queue)


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


abc.TaskGroup.register(CurioTaskGroup)
abc.Lock.register(Lock)
abc.Condition.register(Condition)
abc.Event.register(Event)
abc.Semaphore.register(Semaphore)
abc.Queue.register(Queue)
