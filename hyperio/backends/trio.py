import sys
from functools import wraps
from typing import Callable

import trio.hazmat
from async_generator import async_generator, yield_, asynccontextmanager

from ..exceptions import MultiError
from .. import interfaces, claim_current_thread, T_Retval, _local


class DummyAwaitable:
    def __await__(self):
        if False:
            yield


dummy_awaitable = DummyAwaitable()


def wrap_as_awaitable(func):
    @wraps(func)
    def wrapper(*args, **kwargs):
        func(*args, **kwargs)
        return dummy_awaitable

    return wrapper


#
# Timeouts and cancellation
#

@asynccontextmanager
@async_generator
async def open_cancel_scope():
    with trio.open_cancel_scope() as cancel_scope:
        cancel_scope.cancel = wrap_as_awaitable(cancel_scope.cancel)
        await yield_(cancel_scope)


@asynccontextmanager
@async_generator
async def move_on_after(seconds):
    with trio.move_on_after(seconds) as s:
        await yield_(s)


@asynccontextmanager
@async_generator
async def fail_after(seconds):
    try:
        with trio.fail_after(seconds) as s:
            await yield_(s)
    except trio.TooSlowError as exc:
        raise TimeoutError().with_traceback(exc.__traceback__) from None


#
# Task groups
#

class TaskGroup:
    __slots__ = '_active', '_nursery'

    def __init__(self, nursery) -> None:
        self._active = True
        self._nursery = nursery
        nursery.cancel_scope.cancel = wrap_as_awaitable(nursery.cancel_scope.cancel)

    @property
    def cancel_scope(self):
        return self._nursery.cancel_scope

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        self._nursery.start_soon(func, *args, name=name)


@asynccontextmanager
@async_generator
async def open_task_group():
    try:
        async with trio.open_nursery() as nursery:
            tg = TaskGroup(nursery)
            await yield_(tg)
            tg._active = False
    except trio.MultiError as exc:
        raise MultiError(exc.exceptions) from None


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    def wrapper():
        asynclib = sys.modules[__name__]
        with claim_current_thread(asynclib):
            _local.portal = portal
            return func(*args)

    portal = trio.BlockingTrioPortal()
    return await trio.run_sync_in_worker_thread(wrapper)


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    return _local.portal.run(func, *args)


#
# Networking
#

class TrioSocketWrapper:
    def __init__(self, socket: trio.socket.SocketType) -> None:
        self._socket = socket

    def __getattr__(self, name):
        return getattr(self._socket, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self._socket.__exit__(*exc_info)

    async def accept(self):
        trio_socket, addr = await self._socket.accept()
        return TrioSocketWrapper(trio_socket), addr


def create_socket(family: int, type: int, proto: int, fileno) -> interfaces.Socket:
    # Return a trio socket object, augmented with async context manager support for compatibility
    trio_socket = trio.socket.socket(family, type, proto, fileno)
    return TrioSocketWrapper(trio_socket)


#
# Synchronization
#

class Event(trio.Event):
    async def set(self) -> None:
        super().set()


class Condition(trio.Condition):
    async def notify(self, n: int = 1) -> None:
        super().notify(n)

    async def notify_all(self) -> None:
        super().notify_all()


run = trio.run
sleep = trio.sleep

Lock = trio.Lock
Semaphore = trio.Semaphore
Queue = trio.Queue

interfaces.TaskGroup.register(TaskGroup)
interfaces.Socket.register(trio.socket.SocketType)
interfaces.Socket.register(TrioSocketWrapper)
interfaces.Lock.register(Lock)
interfaces.Condition.register(Condition)
interfaces.Event.register(Event)
interfaces.Semaphore.register(Semaphore)
interfaces.Queue.register(Queue)
