import socket
import ssl
import sys
import threading
import typing  # noqa: F401
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from ssl import SSLContext
from typing import TypeVar, Callable, Union, Optional, Awaitable, Coroutine, Any, Dict

from .interfaces import (  # noqa: F401
    IPAddressType, CancelScope, DatagramSocket, Lock, Condition, Event, Semaphore, Queue,
    TaskGroup, Socket, Stream, SocketStreamServer, SocketStream)

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


def run(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args,
        backend: str = 'asyncio', backend_options: Optional[Dict[str, Any]] = None) -> T_Retval:
    """
    Run the given coroutine function in an asynchronous event loop.

    The current thread must not be already running an event loop.

    :param func: a coroutine function
    :param args: positional arguments to ``func``
    :param backend: name of the asynchronous event loop implementation – one of ``asyncio``,
        ``curio`` and ``trio``
    :param backend_options: keyword arguments to call the backend ``run()`` implementation with
    :return: the return value of the coroutine function

    """
    assert not hasattr(_local, 'asynclib')
    try:
        asynclib = import_module('{}.backends.{}'.format(__name__, backend))
    except ImportError as exc:
        raise LookupError('No such backend: {}'.format(backend)) from exc

    backend_options = backend_options or {}
    with claim_current_thread(asynclib, True):
        return asynclib.run(func, *args, **backend_options)


def is_in_event_loop_thread() -> bool:
    """
    Determine whether the current thread is running a recognized asynchronous event loop.

    :return: ``True`` if running in the event loop, thread, ``False`` if not

    """
    return getattr(_local, 'is_event_loop_thread', False)


#
# Timeouts and cancellation
#

def sleep(delay: float) -> Awaitable[None]:
    """
    Pause the current task for the specified duration.

    :param delay: the duration, in seconds

    """
    return _get_asynclib().sleep(delay)


def open_cancel_scope() -> 'typing.AsyncContextManager[CancelScope]':
    """
    Open a cancel scope.

    :return: an asynchronous context manager that yields a cancel scope.

    """
    return _get_asynclib().open_cancel_scope()


def fail_after(delay: float) -> 'typing.AsyncContextManager[None]':
    """
    Create a context manager which raises an exception if does not finish in time.

    :param delay: maximum allowed time (in seconds) before raising the exception
    :return: an asynchronous context manager
    :raises TimeoutError: if the block does not complete within the allotted time

    """
    return _get_asynclib().fail_after(delay)


def move_on_after(delay: float) -> 'typing.AsyncContextManager[None]':
    """
    Create a context manager which is exited if it does not complete within the given time.

    :param delay: maximum allowed time (in seconds) before exiting the context block
    :return: an asynchronous context manager

    """
    return _get_asynclib().move_on_after(delay)


#
# Task groups
#

def create_task_group() -> 'typing.AsyncContextManager[TaskGroup]':
    """
    Create a task group.

    :return: an asynchronous context manager that yields a task group

    """
    return _get_asynclib().create_task_group()


#
# Threads
#

def run_in_thread(func: Callable[..., T_Retval], *args) -> Awaitable[T_Retval]:
    """
    Start a thread that calls the given function with the given arguments.

    :param func: a callable
    :param args: positional arguments for the callable
    :return: an awaitable that yields the return value of the function.

    """
    assert is_in_event_loop_thread()
    return _get_asynclib().run_in_thread(func, *args)


def run_async_from_thread(func: Callable[..., Coroutine], *args) -> T_Retval:
    """
    Call a coroutine function from a worker thread.

    :param func: a coroutine function
    :param args: positional arguments for the callable
    :return: the return value of the coroutine function

    """
    assert not is_in_event_loop_thread()
    return _get_asynclib().run_async_from_thread(func, *args)


#
# Networking
#

def wait_socket_readable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket has data to be read.

    :param sock: a socket object

    """
    return _get_asynclib().wait_socket_readable(sock)


def wait_socket_writable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket can be written to.

    :param sock: a socket object

    """
    return _get_asynclib().wait_socket_writable(sock)


def connect_tcp(
    address: IPAddressType, port: int, *, tls: Union[bool, SSLContext] = False,
    bind_host: Optional[IPAddressType] = None, bind_port: Optional[int] = None
) -> 'typing.AsyncContextManager[SocketStream]':
    """
    Connect to a host using the TCP protocol.

    :param address: the IP address or host name to connect to
    :param port: port on the target host to connect to
    :param tls: ``False`` to not do a TLS handshake, ``True`` to do the TLS handshake using a
        default context, or an SSL context object to use for the TLS handshake
    :param bind_host: the interface address or name to bind the socket to before connecting
    :param bind_port: the port to bind the socket to before connecting
    :return: an asynchronous context manager that yields a socket stream

    """
    if bind_host:
        bind_host = str(bind_host)

    return _get_asynclib().connect_tcp(str(address), port, tls=tls, bind_host=bind_host,
                                       bind_port=bind_port)


def connect_unix(path: Union[str, Path]) -> 'typing.AsyncContextManager[SocketStream]':
    """
    Connect to the given UNIX socket.

    Not available on Windows.

    :param path: path to the socket
    :return: an asynchronous context manager that yields a socket stream

    """
    return _get_asynclib().connect_unix(str(path))


def create_tcp_server(
    port: int = 0, interface: Optional[IPAddressType] = None,
    ssl_context: Optional[SSLContext] = None
) -> 'typing.AsyncContextManager[SocketStreamServer]':
    """
    Start a TCP socket server.

    :param port: port number to listen on
    :param interface: interface to listen on (if omitted, listen on any interface)
    :param ssl_context: an SSL context object for TLS negotiation
    :return: an asynchronous context manager that yields a server object

    """
    if interface:
        interface = str(interface)

    return _get_asynclib().create_tcp_server(port, interface, ssl_context=ssl_context)


def create_unix_server(
    path: Union[str, Path], *, mode: Optional[int] = None
) -> 'typing.AsyncContextManager[SocketStreamServer]':
    """
    Start a UNIX socket server.

    Not available on Windows.

    :param path: path of the socket
    :param mode: permissions to set on the socket
    :return: an asynchronous context manager that yields a server object

    """
    return _get_asynclib().create_unix_server(str(path), mode=mode)


def create_udp_socket(
    *, interface: Optional[IPAddressType] = None, port: Optional[int] = None,
    target_host: Optional[IPAddressType] = None, target_port: Optional[int] = None
) -> 'typing.AsyncContextManager[DatagramSocket]':
    """
    Create a UDP socket.

    If ``port`` has been given, the socket will be bound to this port on the local machine,
    making this socket suitable for providing UDP based services.

    :param interface: interface to bind to
    :param port: port to bind to
    :param target_host: remote host to set as the default target
    :param target_port: port on the remote host to set as the default target
    :return: a UDP socket

    """
    if interface:
        interface = str(interface)
    if target_host:
        target_host = str(target_host)

    return _get_asynclib().create_udp_socket(bind_host=interface, bind_port=port,
                                             target_host=target_host, target_port=target_port)


#
# Synchronization
#

def create_lock() -> Lock:
    """
    Create an asynchronous lock.

    :return: a lock object

    """
    return _get_asynclib().Lock()


def create_condition() -> Condition:
    """
    Create an asynchronous condition.

    :return: a condition object

    """
    return _get_asynclib().Condition()


def create_event() -> Event:
    """
    Create an asynchronous event object.

    :return: an event object

    """
    return _get_asynclib().Event()


def create_semaphore(value: int) -> Semaphore:
    """
    Create an asynchronous semaphore.

    :param value: the semaphore's initial value
    :return: a semaphore object

    """
    return _get_asynclib().Semaphore(value)


def create_queue(capacity: int) -> Queue:
    """
    Create an asynchronous queue.

    :param capacity: maximum number of items the queue will be able to store
    :return: a queue object

    """
    return _get_asynclib().Queue(capacity)
