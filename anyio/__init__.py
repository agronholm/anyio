import os
import socket
import ssl
import sys
import threading
import typing  # noqa: F401
from contextlib import contextmanager
from importlib import import_module
from inspect import ismodule
from pathlib import Path
from ssl import SSLContext
from typing import TypeVar, Callable, Union, Optional, Awaitable, Coroutine, Any, Dict

from .abc import (  # noqa: F401
    IPAddressType, BufferType, CancelScope, DatagramSocket, Lock, Condition, Event, Semaphore,
    Queue, TaskGroup, Stream, SocketStreamServer, SocketStream, AsyncFile)
from . import _networking

T_Retval = TypeVar('T_Retval', covariant=True)
_local = threading.local()


class NullAsyncContext:
    async def __aenter__(self) -> None:
        return None

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> None:
        pass


@contextmanager
def claim_current_thread(asynclib) -> None:
    assert ismodule(asynclib)
    _local.asynclib = asynclib
    try:
        yield
    finally:
        reset_detected_asynclib()


def reset_detected_asynclib():
    _local.__dict__.clear()


def detect_running_asynclib() -> Optional[str]:
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
        from ._backends.asyncio import get_running_loop
        try:
            get_running_loop()
        except RuntimeError:
            pass
        else:
            return 'asyncio'

    return None


def _get_asynclib():
    try:
        return _local.asynclib
    except AttributeError:
        asynclib_name = detect_running_asynclib()
        if asynclib_name is None:
            raise LookupError('Cannot find any running async event loop')

        _local.asynclib = import_module('{}._backends.{}'.format(__name__, asynclib_name))
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
    :raises RuntimeError: if an asynchronous event loop is already running in this thread
    :raises LookupError: if the named backend is not found

    """
    asynclib_name = detect_running_asynclib()
    if asynclib_name:
        raise RuntimeError('Already running {} in this thread'.format(asynclib_name))

    try:
        asynclib = import_module('{}._backends.{}'.format(__name__, backend))
    except ImportError as exc:
        raise LookupError('No such backend: {}'.format(backend)) from exc

    backend_options = backend_options or {}
    with claim_current_thread(asynclib):
        return asynclib.run(func, *args, **backend_options)


def is_in_event_loop_thread() -> bool:
    """
    Determine whether the current thread is running a recognized asynchronous event loop.

    :return: ``True`` if running in the event loop, thread, ``False`` if not

    """
    return detect_running_asynclib() is not None


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


def fail_after(delay: Optional[float]) -> 'typing.AsyncContextManager[None]':
    """
    Create a context manager which raises an exception if does not finish in time.

    :param delay: maximum allowed time (in seconds) before raising the exception, or ``None`` to
        disable the timeout
    :return: an asynchronous context manager
    :raises TimeoutError: if the block does not complete within the allotted time

    """
    if delay is None:
        return NullAsyncContext()
    else:
        return _get_asynclib().fail_after(delay)


def move_on_after(delay: Optional[float]) -> 'typing.AsyncContextManager[None]':
    """
    Create a context manager which is exited if it does not complete within the given time.

    :param delay: maximum allowed time (in seconds) before exiting the context block, or ``None``
        to disable the timeout
    :return: an asynchronous context manager

    """
    if delay is None:
        return NullAsyncContext()
    else:
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


def run_async_from_thread(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args) -> T_Retval:
    """
    Call a coroutine function from a worker thread.

    :param func: a coroutine function
    :param args: positional arguments for the callable
    :return: the return value of the coroutine function

    """
    assert not is_in_event_loop_thread()
    return _get_asynclib().run_async_from_thread(func, *args)


#
# Async file I/O
#

def aopen(file: Union[str, Path, int], mode: str = 'r', buffering: int = -1,
          encoding: Optional[str] = None, errors: Optional[str] = None,
          newline: Optional[str] = None, closefd: bool = True,
          opener: Optional[Callable] = None) -> Coroutine[Any, Any, AsyncFile]:
    """
    Open a file asynchronously.

    The arguments are exactly the same as for the builtin :func:`open`.

    :return: an asynchronous file object

    """
    if isinstance(file, Path):
        file = str(file)

    return _get_asynclib().aopen(file, mode, buffering, encoding, errors, newline, closefd, opener)


#
# Networking
#

def wait_socket_readable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket has data to be read.

    :param sock: a socket object
    :raises anyio.exceptions.ClosedResourceError: if the socket is closed while waiting

    """
    return _get_asynclib().wait_socket_readable(sock)


def wait_socket_writable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket can be written to.

    :param sock: a socket object
    :raises anyio.exceptions.ClosedResourceError: if the socket is closed while waiting

    """
    return _get_asynclib().wait_socket_writable(sock)


async def connect_tcp(
    address: IPAddressType, port: int, *, ssl_context: Optional[SSLContext] = None,
    autostart_tls: bool = False, bind_host: Optional[IPAddressType] = None,
    bind_port: Optional[int] = None
) -> SocketStream:
    """
    Connect to a host using the TCP protocol.

    :param address: the IP address or host name to connect to
    :param port: port on the target host to connect to
    :param ssl_context: default SSL context to use for TLS handshakes
    :param autostart_tls: ``True`` to do a TLS handshake on connect
    :param bind_host: the interface address or name to bind the socket to before connecting
    :param bind_port: the port to bind the socket to before connecting
    :return: an asynchronous context manager that yields a socket stream

    """
    if bind_host:
        bind_host = str(bind_host)

    raw_socket = socket.socket()
    sock = _get_asynclib().Socket(raw_socket)
    try:
        if bind_host is not None and bind_port is not None:
            await sock.bind((bind_host, bind_port))

        await sock.connect((address, port))
        stream = _networking.SocketStream(sock, ssl_context, address)

        if autostart_tls:
            await stream.start_tls()

        return stream
    except BaseException:
        await sock.close()
        raise


async def connect_unix(path: Union[str, Path]) -> SocketStream:
    """
    Connect to the given UNIX socket.

    Not available on Windows.

    :param path: path to the socket
    :return: an asynchronous context manager that yields a socket stream

    """
    raw_socket = socket.socket(socket.AF_UNIX)
    sock = _get_asynclib().Socket(raw_socket)
    try:
        await sock.connect(path)
        return _networking.SocketStream(sock)
    except BaseException:
        await sock.close()
        raise


async def create_tcp_server(
    port: int = 0, interface: Optional[IPAddressType] = None,
    ssl_context: Optional[SSLContext] = None, autostart_tls: bool = True
) -> SocketStreamServer:
    """
    Start a TCP socket server.

    :param port: port number to listen on
    :param interface: interface to listen on (if omitted, listen on any interface)
    :param ssl_context: an SSL context object for TLS negotiation
    :param autostart_tls: automatically do the TLS handshake on new connections if ``ssl_context``
        has been provided
    :return: an asynchronous context manager that yields a server object

    """
    if interface:
        interface = str(interface)

    raw_socket = socket.socket()
    sock = _get_asynclib().Socket(raw_socket)
    try:
        await sock.bind((interface or '', port))
        sock.listen()
        return _networking.SocketStreamServer(sock, ssl_context, autostart_tls)
    except BaseException:
        await sock.close()
        raise


async def create_unix_server(
        path: Union[str, Path], *, mode: Optional[int] = None) -> SocketStreamServer:
    """
    Start a UNIX socket server.

    Not available on Windows.

    :param path: path of the socket
    :param mode: permissions to set on the socket
    :return: an asynchronous context manager that yields a server object

    """
    raw_socket = socket.socket(socket.AF_UNIX)
    sock = _get_asynclib().Socket(raw_socket)
    try:
        await sock.bind(path)

        if mode is not None:
            os.chmod(path, mode)

        sock.listen()
        return _networking.SocketStreamServer(sock, None, False)
    except BaseException:
        await sock.close()
        raise


async def create_udp_socket(
    *, interface: Optional[IPAddressType] = None, port: Optional[int] = None,
    target_host: Optional[IPAddressType] = None, target_port: Optional[int] = None
) -> DatagramSocket:
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

    raw_socket = socket.socket(type=socket.SOCK_DGRAM)
    sock = _get_asynclib().Socket(raw_socket)
    try:
        if interface is not None or port is not None:
            await sock.bind((interface or '', port or 0))

        if target_host is not None and target_port is not None:
            await sock.connect((target_host, target_port))

        return _networking.DatagramSocket(sock)
    except BaseException:
        await sock.close()
        raise


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


#
# Signal handling
#

def receive_signals(*signals: int) -> 'typing.ContextManager[typing.AsyncIterator[int]]':
    """
    Start receiving operating system signals.

    :param signals: signals to receive (e.g. ``signal.SIGINT``)
    :return: an asynchronous context manager for an asynchronous iterator which yields signal
        numbers

    .. warning:: Windows does not support signals natively so it is best to avoid relying on this
        in cross-platform applications.

    """
    return _get_asynclib().receive_signals(*signals)


#
# Testing and debugging
#

async def wait_all_tasks_blocked() -> None:
    """Wait until all other tasks are waiting for something."""
    await _get_asynclib().wait_all_tasks_blocked()
