import os
import socket
import ssl
import sys
import threading
import typing
from contextlib import contextmanager
from importlib import import_module
from pathlib import Path
from ssl import SSLContext
from typing import TypeVar, Callable, Union, Optional, Awaitable, Coroutine, Any, Dict

import sniffio

from .abc import (  # noqa: F401
    IPAddressType, CancelScope, UDPSocket, Lock, Condition, Event, Semaphore, Queue, TaskGroup,
    Stream, SocketStreamServer, SocketStream, AsyncFile)
from . import _networking

BACKENDS = 'asyncio', 'curio', 'trio'

T_Retval = TypeVar('T_Retval', covariant=True)
T_Agen = TypeVar('T_Agen')
_local = threading.local()


#
# Event loop
#

def run(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args,
        backend: str = BACKENDS[0], backend_options: Optional[Dict[str, Any]] = None) -> T_Retval:
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
    asynclib_name = _detect_running_asynclib()
    if asynclib_name:
        raise RuntimeError('Already running {} in this thread'.format(asynclib_name))

    try:
        asynclib = import_module('{}._backends.{}'.format(__name__, backend))
    except ImportError as exc:
        raise LookupError('No such backend: {}'.format(backend)) from exc

    token = None
    if sniffio.current_async_library_cvar.get(None) is None:
        # Since we're in control of the event loop, we can cache the name of the async library
        token = sniffio.current_async_library_cvar.set(backend)

    try:
        backend_options = backend_options or {}
        return asynclib.run(func, *args, **backend_options)  # type: ignore
    finally:
        if token:
            sniffio.current_async_library_cvar.reset(token)


@contextmanager
def claim_worker_thread(backend) -> typing.Generator[Any, None, None]:
    module = sys.modules['anyio._backends.' + backend]
    _local.current_async_module = module
    token = sniffio.current_async_library_cvar.set(backend)
    try:
        yield
    finally:
        sniffio.current_async_library_cvar.reset(token)
        del _local.current_async_module


def _detect_running_asynclib() -> Optional[str]:
    # This function can be removed once https://github.com/python-trio/sniffio/pull/5 has been
    # merged
    try:
        return sniffio.current_async_library()
    except sniffio.AsyncLibraryNotFoundError:
        if 'curio' in sys.modules:
            from curio.meta import curio_running
            if curio_running():
                return 'curio'

        return None


def _get_asynclib():
    asynclib_name = _detect_running_asynclib()
    if asynclib_name is None:
        raise RuntimeError('Not running in any supported asynchronous event loop')

    modulename = 'anyio._backends.' + asynclib_name
    try:
        return sys.modules[modulename]
    except KeyError:
        return import_module(modulename)


#
# Miscellaneous
#

def finalize(resource: T_Agen) -> 'typing.AsyncContextManager[T_Agen]':
    """
    Return a context manager that automatically closes an asynchronous resource on exit.

    :param resource: an asynchronous generator or other resource with an ``aclose()`` method
    :return: an asynchronous context manager that yields the given object

    """
    # This exists solely because curio is being a special snowflake and doesn't accept
    # async_generator.aclosing(). See https://github.com/dabeaz/curio/issues/176.
    return _get_asynclib().finalize(resource)


def sleep(delay: float) -> Coroutine[Any, Any, None]:
    """
    Pause the current task for the specified duration.

    :param delay: the duration, in seconds

    """
    return _get_asynclib().sleep(delay)


#
# Timeouts and cancellation
#

def open_cancel_scope(*, shield: bool = False) -> 'typing.AsyncContextManager[CancelScope]':
    """
    Open a cancel scope.

    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope

    """
    return _get_asynclib().open_cancel_scope(shield=shield)


def fail_after(delay: Optional[float], *,
               shield: bool = False) -> 'typing.AsyncContextManager[CancelScope]':
    """
    Create a context manager which raises an exception if does not finish in time.

    :param delay: maximum allowed time (in seconds) before raising the exception, or ``None`` to
        disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope
    :raises TimeoutError: if the block does not complete within the allotted time

    """
    if delay is None:
        return _get_asynclib().open_cancel_scope(shield=shield)
    else:
        return _get_asynclib().fail_after(delay, shield=shield)


def move_on_after(delay: Optional[float], *,
                  shield: bool = False) -> 'typing.AsyncContextManager[CancelScope]':
    """
    Create a context manager which is exited if it does not complete within the given time.

    :param delay: maximum allowed time (in seconds) before exiting the context block, or ``None``
        to disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope

    """
    if delay is None:
        return _get_asynclib().open_cancel_scope(shield=shield)
    else:
        return _get_asynclib().move_on_after(delay, shield=shield)


def current_effective_deadline() -> Coroutine[Any, Any, float]:
    """
    Return the nearest deadline among all the cancel scopes effective for the current task.

    :return: a clock value from the event loop's internal clock (``float('inf')`` if there is no
        deadline in effect)
    :rtype: float

    """
    return _get_asynclib().current_effective_deadline()


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
    return _get_asynclib().run_in_thread(func, *args)


def run_async_from_thread(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args) -> T_Retval:
    """
    Call a coroutine function from a worker thread.

    :param func: a coroutine function
    :param args: positional arguments for the callable
    :return: the return value of the coroutine function

    """
    try:
        asynclib = _local.current_async_module
    except AttributeError:
        raise RuntimeError('This function can only be run from an AnyIO worker thread')

    return asynclib.run_async_from_thread(func, *args)


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
    :rtype: AsyncFile

    """
    if isinstance(file, Path):
        file = str(file)

    return _get_asynclib().aopen(file, mode, buffering, encoding, errors, newline, closefd, opener)


#
# Sockets and networking
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
    bind_port: Optional[int] = None, tls_standard_compatible: bool = True
) -> SocketStream:
    """
    Connect to a host using the TCP protocol.

    :param address: the IP address or host name to connect to
    :param port: port on the target host to connect to
    :param ssl_context: default SSL context to use for TLS handshakes
    :param autostart_tls: ``True`` to do a TLS handshake on connect
    :param bind_host: the interface address or name to bind the socket to before connecting
    :param bind_port: the port to bind the socket to before connecting
    :param tls_standard_compatible: If ``True``, performs the TLS shutdown handshake before closing
        the stream and requires that the server does this as well. Otherwise,
        :exc:`~ssl.SSLEOFError` may be raised during reads from the stream.
        Some protocols, such as HTTP, require this option to be ``False``.
        See :meth:`~ssl.SSLContext.wrap_socket` for details.
    :return: an asynchronous context manager that yields a socket stream

    """
    if bind_host:
        bind_host = str(bind_host)

    raw_socket = socket.socket()
    sock = _get_asynclib().Socket(raw_socket)
    try:
        sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
        if bind_host is not None and bind_port is not None:
            await sock.bind((bind_host, bind_port))

        await sock.connect((address, port))
        stream = _networking.SocketStream(sock, ssl_context, str(address), tls_standard_compatible)

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
    ssl_context: Optional[SSLContext] = None, autostart_tls: bool = True,
    tls_standard_compatible: bool = True,
) -> SocketStreamServer:
    """
    Start a TCP socket server.

    :param port: port number to listen on
    :param interface: interface to listen on (if omitted, listen on any interface)
    :param ssl_context: an SSL context object for TLS negotiation
    :param autostart_tls: automatically do the TLS handshake on new connections if ``ssl_context``
        has been provided
    :param tls_standard_compatible: If ``True``, performs the TLS shutdown handshake before closing
        a connected stream and requires that the client does this as well. Otherwise,
        :exc:`~ssl.SSLEOFError` may be raised during reads from a client stream.
        Some protocols, such as HTTP, require this option to be ``False``.
        See :meth:`~ssl.SSLContext.wrap_socket` for details.
    :return: an asynchronous context manager that yields a server object

    """
    if interface:
        interface = str(interface)

    raw_socket = socket.socket()
    sock = _get_asynclib().Socket(raw_socket)
    try:
        if sys.platform == 'win32':
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        else:
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

        await sock.bind((interface or '', port))
        sock.listen()
        return _networking.SocketStreamServer(sock, ssl_context, autostart_tls,
                                              tls_standard_compatible)
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
        return _networking.SocketStreamServer(sock, None, False, True)
    except BaseException:
        await sock.close()
        raise


async def create_udp_socket(
    *, interface: Optional[IPAddressType] = None, port: Optional[int] = None,
    target_host: Optional[IPAddressType] = None, target_port: Optional[int] = None
) -> UDPSocket:
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

        return _networking.UDPSocket(sock)
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
# Operating system signals
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
