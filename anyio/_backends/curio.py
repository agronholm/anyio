import math
import socket  # noqa: F401
from functools import partial
from typing import Callable, Set, Optional, Coroutine, Any, cast, Dict, List  # noqa: F401

import curio.io
import curio.meta
import curio.socket
import curio.ssl
import curio.traps
from async_generator import async_generator, asynccontextmanager, yield_

from .._networking import BaseSocket
from .. import abc, T_Retval, claim_worker_thread, _local, TaskInfo
from ..exceptions import ExceptionGroup, CancelledError, ClosedResourceError, ResourceBusyError


#
# Event loop
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
        return cast(T_Retval, retval)


#
# Miscellaneous functions
#

finalize = curio.meta.finalize


async def sleep(delay: float):
    await check_cancelled()
    await curio.sleep(delay)


#
# Timeouts and cancellation
#

class CancelScope:
    __slots__ = ('_deadline', '_shield', '_parent_scope', '_cancel_called', '_active',
                 '_timeout_task', '_tasks', '_timeout_expired')

    def __init__(self, deadline: float = math.inf, shield: bool = False):
        self._deadline = deadline
        self._shield = shield
        self._parent_scope = None
        self._cancel_called = False
        self._active = False
        self._timeout_task = None
        self._tasks = set()  # type: Set[curio.Task]
        self._timeout_expired = False

    async def __aenter__(self):
        async def timeout():
            await curio.sleep(self._deadline - await curio.clock())
            self._timeout_expired = True
            await self.cancel()

        if self._active:
            raise RuntimeError(
                "Each CancelScope may only be used for a single 'async with' block"
            )

        host_task = await curio.current_task()
        self._parent_scope = get_cancel_scope(host_task)
        self._tasks.add(host_task)
        set_cancel_scope(host_task, self)

        if self._deadline != math.inf:
            self._timeout_task = await curio.spawn(timeout)

        self._active = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._active = False
        if self._timeout_task:
            await self._timeout_task.cancel(blocking=False)

        host_task = await curio.current_task()
        self._tasks.remove(host_task)
        set_cancel_scope(host_task, self._parent_scope)

        if isinstance(exc_val, curio.TaskCancelled):
            if self._timeout_expired:
                return True
            elif self._cancel_called:
                # This scope was directly cancelled
                return True

    async def cancel(self):
        if self._cancel_called:
            return

        self._cancel_called = True

        # Cancel any contained tasks
        for task in self._tasks:
            if task.coro.cr_await is not None and not task.coro.cr_running:
                # Cancel the task directly, but only if it's blocked and isn't within a shielded
                # scope
                scope = get_cancel_scope(task)
                if scope is self or not scope.shield:
                    await task.cancel(blocking=False)

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def cancel_called(self) -> bool:
        return self._cancel_called

    @property
    def shield(self) -> bool:
        return self._shield


abc.CancelScope.register(CancelScope)


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
    if cancel_scope is not None and not cancel_scope._shield and cancel_scope._cancel_called:
        raise CancelledError


@asynccontextmanager
@async_generator
async def fail_after(delay: float, shield: bool):
    deadline = await curio.clock() + delay
    async with CancelScope(deadline, shield) as scope:
        await yield_(scope)

    if scope._timeout_expired:
        raise TimeoutError


@asynccontextmanager
@async_generator
async def move_on_after(delay: float, shield: bool):
    deadline = await curio.clock() + delay
    async with CancelScope(deadline=deadline, shield=shield) as scope:
        await yield_(scope)


async def current_effective_deadline():
    deadline = math.inf
    cancel_scope = get_cancel_scope(await curio.current_task())
    while cancel_scope:
        deadline = min(deadline, cancel_scope.deadline)
        cancel_scope = cancel_scope._parent_scope

    return deadline


#
# Task groups
#

class TaskGroup:
    __slots__ = 'cancel_scope', '_active'

    def __init__(self) -> None:
        self.cancel_scope = CancelScope()
        self._active = False

    async def __aenter__(self):
        await self.cancel_scope.__aenter__()
        self._active = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.cancel_scope.__aexit__(exc_type, exc_val, exc_tb)

        exceptions = []  # type: List[BaseException]
        ignore_exception = False
        if exc_val is not None:
            await self.cancel_scope.cancel()
            if not isinstance(exc_val, (curio.TaskCancelled, CancelledError)):
                exceptions.append(exc_val)
            elif not self.cancel_scope._parent_scope:
                ignore_exception = True
            elif not self.cancel_scope._parent_scope.cancel_called:
                ignore_exception = True

        while self.cancel_scope._tasks:
            for task in self.cancel_scope._tasks.copy():
                try:
                    await task.join()
                except (curio.TaskCancelled, curio.TaskError):
                    set_cancel_scope(task, None)
                    self.cancel_scope._tasks.remove(task)
                    if not isinstance(task.next_exc, (curio.TaskCancelled, CancelledError)):
                        exceptions.append(task.next_exc)

        self._active = False
        if len(exceptions) > 1:
            raise ExceptionGroup(exceptions)
        elif exceptions and exceptions[0] is not exc_val:
            raise exceptions[0]

        return ignore_exception

    async def _run_wrapped_task(self, func, *args):
        task = await curio.current_task()
        try:
            await func(*args)
        except BaseException:
            await self.cancel_scope.cancel()
            raise
        else:
            set_cancel_scope(task, None)
            self.cancel_scope._tasks.remove(task)

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        task = await curio.spawn(self._run_wrapped_task, func, *args, daemon=True,
                                 report_crash=False)
        task.parentid = (await curio.current_task()).id
        if name is not None:
            task.name = name

        # Make the spawned task inherit the task group's cancel scope
        self.cancel_scope._tasks.add(task)
        set_cancel_scope(task, self.cancel_scope)


abc.TaskGroup.register(TaskGroup)


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    def thread_worker():
        with claim_worker_thread('curio'):
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
# Sockets and networking
#

_reader_tasks = {}  # type: Dict[socket.SocketType, curio.Task]
_writer_tasks = {}  # type: Dict[socket.SocketType, curio.Task]


class Socket(BaseSocket):
    __slots__ = ()

    def _wait_readable(self):
        return wait_socket_readable(self._raw_socket)

    def _wait_writable(self):
        return wait_socket_writable(self._raw_socket)

    def _notify_close(self):
        return notify_socket_close(self._raw_socket)

    def _check_cancelled(self) -> Coroutine[Any, Any, None]:
        return check_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


async def wait_socket_readable(sock):
    await check_cancelled()
    if _reader_tasks.get(sock):
        raise ResourceBusyError('reading from') from None

    _reader_tasks[sock] = await curio.current_task()
    try:
        return await curio.traps._read_wait(sock)
    except curio.TaskCancelled:
        if sock.fileno() == -1:
            raise ClosedResourceError from None
        else:
            raise
    finally:
        del _reader_tasks[sock]


async def wait_socket_writable(sock):
    await check_cancelled()
    if _writer_tasks.get(sock):
        raise ResourceBusyError('writing to') from None

    _writer_tasks[sock] = await curio.current_task()
    try:
        return await curio.traps._write_wait(sock)
    except curio.TaskCancelled:
        if sock.fileno() == -1:
            raise ClosedResourceError from None
        else:
            raise
    finally:
        del _writer_tasks[sock]


async def notify_socket_close(sock: socket.SocketType):
    for tasks_map in _reader_tasks, _writer_tasks:
        task = tasks_map.get(sock)
        if task is not None:
            await task.cancel(blocking=False)


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
# Operating system signals
#

@asynccontextmanager
@async_generator
async def receive_signals(*signals: int):
    async with curio.SignalQueue(*signals) as queue:
        await yield_(queue)


#
# Testing and debugging
#

async def get_current_task() -> TaskInfo:
    task = await curio.current_task()
    return TaskInfo(task.id, task.parentid, task.name, task.coro)


async def get_running_tasks() -> List[TaskInfo]:
    task_infos = []
    kernel = await curio.traps._get_kernel()
    for task in kernel._tasks.values():
        if not task.terminated:
            task_infos.append(TaskInfo(task.id, task.parentid, task.name, task.coro))

    return task_infos


async def wait_all_tasks_blocked() -> None:
    this_task = await curio.current_task()
    kernel = await curio.traps._get_kernel()
    while True:
        for task in kernel._tasks.values():
            if task.id != this_task.id and task.coro.cr_await is None:
                await curio.sleep(0)
                break
        else:
            return
