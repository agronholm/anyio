import sys
import threading
import typing  # noqa: F401
from _socket import AF_INET, SOCK_STREAM
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from ssl import SSLContext
from typing import TypeVar, Callable, Union, Iterable, Optional, AsyncIterable, Awaitable

from .interfaces import (  # noqa: F401
    IPAddressType, StreamingSocket, CancelScope, DatagramSocket, Lock,
    Condition, Event, Semaphore, Queue, TaskGroup, Socket)

T_Retval = TypeVar('T_Retval', covariant=True)
_local = threading.local()


@contextmanager
def claim_current_thread(asynclib, is_event_loop_thread: bool = False) -> None:
    _local.asynclib = asynclib
    _local.is_event_loop_thread = is_event_loop_thread
    try:
        yield
    finally:
        _local.__dict__.clear()


def run(func: Callable[..., T_Retval], *args, backend: str = 'asyncio') -> T_Retval:
    assert not hasattr(_local, 'asynclib')
    try:
        asynclib = import_module('{}.backends.{}'.format(__name__, backend))
    except ImportError as exc:
        raise LookupError('No such backend: {}'.format(backend)) from exc

    with claim_current_thread(asynclib, True):
        return asynclib.run(func, *args)


def is_in_event_loop_thread() -> bool:
    return getattr(_local, 'is_event_loop_thread', False)


def _detect_running_asynclib() -> str:
    if 'trio' in sys.modules:
        from trio.hazmat import current_trio_token
        try:
            current_trio_token()
        except RuntimeError:
            pass
        else:
            return 'trio'

    if 'curio' in sys.modules:
        from curio.meta import curio_running
        if curio_running():
            return 'curio'

    if 'asyncio' in sys.modules:
        from .backends.asyncio import get_running_loop
        if get_running_loop() is not None:
            return 'asyncio'

    raise LookupError('Cannot find any running async event loop')


def _get_asynclib():
    try:
        return _local.asynclib
    except AttributeError:
        asynclib_name = _detect_running_asynclib()
        _local.asynclib = import_module('{}.backends.{}'.format(__name__, asynclib_name))
        return _local.asynclib


#
# Timeouts and cancellation
#

def get_cancelled_error() -> BaseException:
    return _get_asynclib().CancelledError


def sleep(delay: float) -> Awaitable[None]:
    return _get_asynclib().sleep(delay)


def open_cancel_scope() -> 'typing.AsyncContextManager[CancelScope]':
    return _get_asynclib().open_cancel_scope()


def fail_after(delay: float) -> 'typing.AsyncContextManager[None]':
    return _get_asynclib().fail_after(delay)


def move_on_after(delay: float) -> 'typing.AsyncContextManager[None]':
    return _get_asynclib().move_on_after(delay)


#
# Concurrency
#

def create_task_group() -> 'typing.AsyncContextManager[TaskGroup]':
    return _get_asynclib().open_task_group()


def run_in_thread(func: Callable[..., T_Retval], *args) -> Awaitable[T_Retval]:
    assert is_in_event_loop_thread()
    return _get_asynclib().run_in_thread(func, *args)


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    assert not is_in_event_loop_thread()
    return _get_asynclib().run_async_from_thread(func, *args)


#
# Networking
#

def create_socket(family: int = AF_INET, type: int = SOCK_STREAM, proto: int = 0,
                  fileno=None) -> Socket:
    return _get_asynclib().create_socket(family, type, proto, fileno)


def connect_tcp(
        address: IPAddressType, port: int, *,
        bind: Union[IPAddressType, Iterable[IPAddressType], None] = None) -> \
        Awaitable[StreamingSocket]:
    return _get_asynclib().connect_tcp(address, port, bind=bind)


def connect_unix(path: Union[str, Path]) -> Awaitable[StreamingSocket]:
    return _get_asynclib().connect_unix(path)


def serve_tcp(
        port: int, *, address: Union[IPAddressType, Iterable[IPAddressType]] = None,
        ssl_context: Optional[SSLContext] = None) -> AsyncIterable[StreamingSocket]:
    return _get_asynclib().serve_tcp(port, address=address, ssl_context=ssl_context)


def create_udp_socket(*, bind: Union[IPAddressType, Iterable[IPAddressType], None] = None,
                      target: Optional[IPAddressType] = None) -> Awaitable[DatagramSocket]:
    return _get_asynclib().create_udp_socket(bind=bind, target=target)


#
# Synchronization
#

def create_lock() -> Lock:
    return _get_asynclib().Lock()


def create_condition() -> Condition:
    return _get_asynclib().Condition()


def create_event() -> Event:
    return _get_asynclib().Event()


def create_semaphore(value: int) -> Semaphore:
    return _get_asynclib().Semaphore(value)


def create_queue(capacity: int) -> Queue:
    return _get_asynclib().Queue(capacity)
