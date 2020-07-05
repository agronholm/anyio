import math
from types import TracebackType
from typing import Callable, Optional, List, Type, Union

import trio.from_thread
from async_generator import async_generator, yield_, asynccontextmanager, aclosing
from trio.to_thread import run_sync

from .. import abc, claim_worker_thread, T_Retval, TaskInfo
from ..exceptions import (
    ExceptionGroup as BaseExceptionGroup, ClosedResourceError, ResourceBusyError, WouldBlock)
from .._networking import BaseSocket

try:
    import trio.lowlevel as trio_lowlevel
except ImportError:
    import trio.hazmat as trio_lowlevel
    from trio.hazmat import wait_readable, wait_writable, notify_closing
else:
    from trio.lowlevel import wait_readable, wait_writable, notify_closing


#
# Event loop
#

run = trio.run


#
# Miscellaneous
#

finalize = aclosing
sleep = trio.sleep


#
# Timeouts and cancellation
#

CancelledError = trio.Cancelled


class CancelScope:
    __slots__ = '__original'

    def __init__(self, original: Optional[trio.CancelScope] = None, **kwargs):
        self.__original = original or trio.CancelScope(**kwargs)

    async def __aenter__(self):
        if self.__original._has_been_entered:
            raise RuntimeError(
                "Each CancelScope may only be used for a single 'async with' block"
            )

        self.__original.__enter__()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        return self.__original.__exit__(exc_type, exc_val, exc_tb)

    async def cancel(self) -> None:
        self.__original.cancel()

    @property
    def deadline(self) -> float:
        return self.__original.deadline

    @property
    def cancel_called(self) -> bool:
        return self.__original.cancel_called

    @property
    def shield(self) -> bool:
        return self.__original.shield


abc.CancelScope.register(CancelScope)


@asynccontextmanager
@async_generator
async def move_on_after(seconds, shield):
    with trio.move_on_after(seconds) as scope:
        scope.shield = shield
        await yield_(CancelScope(scope))


@asynccontextmanager
@async_generator
async def fail_after(seconds, shield):
    try:
        with trio.fail_after(seconds) as cancel_scope:
            cancel_scope.shield = shield
            await yield_(CancelScope(cancel_scope))
    except trio.TooSlowError as exc:
        raise TimeoutError().with_traceback(exc.__traceback__) from None


async def current_effective_deadline():
    return trio.current_effective_deadline()


async def current_time():
    return trio.current_time()


#
# Task groups
#

class ExceptionGroup(BaseExceptionGroup, trio.MultiError):
    pass


class TaskGroup:
    __slots__ = '_active', '_nursery_manager', '_nursery', 'cancel_scope'

    def __init__(self) -> None:
        self._active = False
        self._nursery_manager = trio.open_nursery()
        self.cancel_scope = None

    async def __aenter__(self):
        self._active = True
        self._nursery = await self._nursery_manager.__aenter__()
        self.cancel_scope = CancelScope(self._nursery.cancel_scope)
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        try:
            return await self._nursery_manager.__aexit__(exc_type, exc_val, exc_tb)
        except trio.MultiError as exc:
            raise ExceptionGroup(exc.exceptions) from None
        finally:
            self._active = False

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        self._nursery.start_soon(func, *args, name=name)


abc.TaskGroup.register(TaskGroup)


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args, cancellable: bool = False,
                        limiter: Optional['CapacityLimiter'] = None) -> T_Retval:
    def wrapper():
        with claim_worker_thread('trio'):
            return func(*args)

    trio_limiter = getattr(limiter, '_limiter', None)
    return await run_sync(wrapper, cancellable=cancellable, limiter=trio_limiter)

run_async_from_thread = trio.from_thread.run


#
# Async file I/O
#

async def aopen(*args, **kwargs):
    f = await trio.open_file(*args, **kwargs)
    f.close = f.aclose
    return f


#
# Sockets and networking
#

class Socket(BaseSocket):
    __slots__ = ()

    def _wait_readable(self):
        return wait_socket_readable(self._raw_socket)

    def _wait_writable(self):
        return wait_socket_writable(self._raw_socket)

    async def _notify_close(self):
        if self._raw_socket.fileno() >= 0:
            notify_closing(self._raw_socket)

    def _check_cancelled(self):
        return trio_lowlevel.checkpoint()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


getaddrinfo = trio.socket.getaddrinfo
getnameinfo = trio.socket.getnameinfo


async def wait_socket_readable(sock):
    try:
        await wait_readable(sock)
    except trio.ClosedResourceError as exc:
        raise ClosedResourceError().with_traceback(exc.__traceback__) from None
    except trio.BusyResourceError:
        raise ResourceBusyError('reading from') from None


async def wait_socket_writable(sock):
    try:
        await wait_writable(sock)
    except trio.ClosedResourceError as exc:
        raise ClosedResourceError().with_traceback(exc.__traceback__) from None
    except trio.BusyResourceError:
        raise ResourceBusyError('writing to') from None


async def notify_socket_close(sock):
    return notify_closing(sock)


#
# Synchronization
#

Lock = trio.Lock


class Event:
    def __init__(self):
        self._event = trio.Event()

    async def set(self) -> None:
        self._event.set()

    def clear(self):
        if self._event.is_set():
            self._event = trio.Event()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self):
        await self._event.wait()


class Condition:
    def __init__(self, lock: Optional[trio.Lock] = None):
        self._cond = trio.Condition(lock=lock)

    async def __aenter__(self):
        await self._cond.__aenter__()

    async def __aexit__(self, *exc_info):
        return await self._cond.__aexit__(*exc_info)

    async def notify(self, n: int = 1) -> None:
        self._cond.notify(n)

    async def notify_all(self) -> None:
        self._cond.notify_all()

    def locked(self):
        return self._cond.locked()

    async def wait(self):
        return await self._cond.wait()


Semaphore = trio.Semaphore


class Queue:
    def __init__(self, max_items: int) -> None:
        max_buffer_size = max_items if max_items > 0 else math.inf
        self._send_channel, self._receive_channel = trio.open_memory_channel(max_buffer_size)

    def empty(self):
        return self._receive_channel.statistics().current_buffer_used == 0

    def full(self):
        statistics = self._receive_channel.statistics()
        return statistics.current_buffer_used >= statistics.max_buffer_size

    def qsize(self) -> int:
        return self._receive_channel.statistics().current_buffer_used

    async def put(self, item) -> None:
        await self._send_channel.send(item)

    async def get(self):
        return await self._receive_channel.receive()

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self._receive_channel.receive()


class CapacityLimiter(abc.CapacityLimiter):
    def __init__(self, limiter_or_tokens: Union[float, trio.CapacityLimiter]):
        if isinstance(limiter_or_tokens, trio.CapacityLimiter):
            self._limiter = limiter_or_tokens
        else:
            self._limiter = trio.CapacityLimiter(limiter_or_tokens)

    async def __aenter__(self) -> 'CapacityLimiter':
        await self._limiter.__aenter__()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        await self._limiter.__aexit__(exc_type, exc_val, exc_tb)

    @property
    def total_tokens(self) -> float:
        return self._limiter.total_tokens

    async def set_total_tokens(self, value: float) -> None:
        self._limiter.total_tokens = value

    @property
    def borrowed_tokens(self) -> int:
        return self._limiter.borrowed_tokens

    @property
    def available_tokens(self) -> float:
        return self._limiter.available_tokens

    async def acquire_nowait(self):
        return self.acquire_nowait()

    async def acquire_on_behalf_of_nowait(self, borrower):
        try:
            return self._limiter.acquire_on_behalf_of_nowait(borrower)
        except trio.WouldBlock as exc:
            raise WouldBlock from exc

    def acquire(self):
        return self._limiter.acquire()

    def acquire_on_behalf_of(self, borrower):
        return self._limiter.acquire_on_behalf_of(borrower)

    async def release(self):
        self._limiter.release()

    async def release_on_behalf_of(self, borrower):
        self._limiter.release_on_behalf_of(borrower)


def current_default_thread_limiter():
    native_limiter = trio.to_thread.current_default_thread_limiter()
    return CapacityLimiter(native_limiter)


abc.Lock.register(Lock)
abc.Condition.register(Condition)
abc.Event.register(Event)
abc.Semaphore.register(Semaphore)
abc.Queue.register(Queue)
abc.CapacityLimiter.register(CapacityLimiter)


#
# Signal handling
#

@asynccontextmanager
@async_generator
async def receive_signals(*signals: int):
    with trio.open_signal_receiver(*signals) as cm:
        await yield_(cm)


#
# Testing and debugging
#

async def get_current_task() -> TaskInfo:
    task = trio_lowlevel.current_task()

    parent_id = None
    if task.parent_nursery and task.parent_nursery.parent_task:
        parent_id = id(task.parent_nursery.parent_task)

    return TaskInfo(id(task), parent_id, task.name, task.coro)


async def get_running_tasks() -> List[TaskInfo]:
    root_task = trio_lowlevel.current_root_task()
    task_infos = [TaskInfo(id(root_task), None, root_task.name, root_task.coro)]
    nurseries = root_task.child_nurseries
    while nurseries:
        new_nurseries = []  # type: List[trio.Nursery]
        for nursery in nurseries:
            for task in nursery.child_tasks:
                task_infos.append(
                    TaskInfo(id(task), id(nursery.parent_task), task.name, task.coro))
                new_nurseries.extend(task.child_nurseries)

        nurseries = new_nurseries

    return task_infos


def wait_all_tasks_blocked():
    import trio.testing
    return trio.testing.wait_all_tasks_blocked()
