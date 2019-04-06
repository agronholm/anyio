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
from ..exceptions import ExceptionGroup, CancelledError, ClosedResourceError


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
    __slots__ = ('_deadline', '_shield', '_parent_scope', '_cancel_called', '_host_task',
                 '_timeout_task', '_timeout_expired')

    def __init__(self, deadline: float = float('inf'), shield: bool = False):
        self._deadline = deadline
        self._shield = shield
        self._parent_scope = None
        self._cancel_called = False
        self._host_task = None
        self._timeout_task = None

    async def __aenter__(self):
        async def timeout():
            await curio.sleep(self._deadline - await curio.clock())
            self._timeout_expired = True
            await self.cancel()

        if self._host_task:
            raise RuntimeError(
                "Each CancelScope may only be used for a single 'async with' block"
            )

        self._host_task = await curio.current_task()
        self._parent_scope = get_cancel_scope(self._host_task)
        set_cancel_scope(self._host_task, self)
        self._timeout_expired = False

        if self._deadline != float('inf'):
            self._timeout_task = await curio.spawn(timeout)

        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        if self._timeout_task:
            await self._timeout_task.cancel()

        set_cancel_scope(self._host_task, self._parent_scope)

        if isinstance(exc_val, curio.TaskCancelled):
            if self._timeout_expired:
                return True
            elif self._cancel_called:
                # This scope was directly cancelled
                return True

    async def cancel(self):
        if not self._cancel_called:
            self._cancel_called = True

            # Check if the host task should be cancelled
            if self._host_task is not await curio.current_task():
                scope = get_cancel_scope(self._host_task)
                while scope and scope is not self:
                    if scope.shield:
                        break
                    else:
                        scope = scope._parent_scope
                else:
                    await self._host_task.cancel(blocking=False)

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
    deadline = float('inf')
    cancel_scope = get_cancel_scope(await curio.current_task())
    while cancel_scope:
        deadline = min(deadline, cancel_scope.deadline)
        cancel_scope = cancel_scope._parent_scope

    return deadline


#
# Task groups
#

class TaskGroup:
    __slots__ = 'cancel_scope', '_active', '_tasks', '_host_task'

    def __init__(self) -> None:
        self.cancel_scope = CancelScope()
        self._active = False
        self._tasks = set()  # type: Set[curio.Task]

    async def __aenter__(self):
        await self.cancel_scope.__aenter__()
        self._active = True
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        exceptions = []
        ignore_exception = False
        if exc_val is not None:
            await self.cancel_scope.cancel()
            if not isinstance(exc_val, (curio.TaskCancelled, CancelledError)):
                exceptions.append(exc_val)
            elif not self.cancel_scope._parent_scope:
                ignore_exception = True
            elif not self.cancel_scope._parent_scope.cancel_called:
                ignore_exception = True

        if self.cancel_scope.cancel_called:
            for task in self._tasks:
                if task.coro.cr_await is not None:
                    await task.cancel(blocking=False)

        while self._tasks:
            for task in set(self._tasks):
                try:
                    await task.join()
                except (curio.TaskCancelled, curio.TaskError):
                    set_cancel_scope(task, None)
                    self._tasks.remove(task)
                    if not isinstance(task.next_exc, (curio.CancelledError, CancelledError)):
                        exceptions.append(task.next_exc)

        self._active = False
        await self.cancel_scope.__aexit__(exc_type, exc_val, exc_tb)

        if len(exceptions) > 1:
            raise ExceptionGroup(exceptions)
        elif exceptions and exceptions[0] is not exc_val:
            raise exceptions[0]

        return ignore_exception

    async def _run_wrapped_task(self, func, *args):
        try:
            await func(*args)
        except BaseException:
            await self.cancel_scope.cancel()
            raise
        else:
            task = await curio.current_task()
            self._tasks.remove(task)
            set_cancel_scope(task, None)

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        task = await curio.spawn(self._run_wrapped_task, func, *args, daemon=True,
                                 report_crash=False)
        task.parentid = self.cancel_scope._host_task.id
        self._tasks.add(task)
        if name is not None:
            task.name = name

        # Make the spawned task inherit the task group's cancel scope
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

class Socket(BaseSocket):
    _reader_tasks = {}  # type: Dict[socket.SocketType, curio.Task]
    _writer_tasks = {}  # type: Dict[socket.SocketType, curio.Task]

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

    def _check_cancelled(self) -> Coroutine[Any, Any, None]:
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
