import os
import socket
import ssl
import sys
import threading
import typing
from contextlib import contextmanager
from importlib import import_module
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
    try:
        asynclib_name = sniffio.current_async_library()
    except sniffio.AsyncLibraryNotFoundError:
        pass
    else:
        raise RuntimeError('Already running {} in this thread'.format(asynclib_name))

    try:
        asynclib = import_module('{}._backends._{}'.format(__name__, backend))
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
    module = sys.modules['anyio._backends._' + backend]
    _local.current_async_module = module
    token = sniffio.current_async_library_cvar.set(backend)
    try:
        yield
    finally:
        sniffio.current_async_library_cvar.reset(token)
        del _local.current_async_module


def _get_asynclib():
    asynclib_name = sniffio.current_async_library()
    modulename = 'anyio._backends._' + asynclib_name
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


def get_cancelled_exc_class() -> typing.Type[BaseException]:
    """Return the current async library's cancellation exception class."""
    return _get_asynclib().CancelledError


#
# Timeouts and cancellation
#

def open_cancel_scope(*, shield: bool = False) -> CancelScope:
    """
    Open a cancel scope.

    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a cancel scope

    """
    return _get_asynclib().CancelScope(shield=shield)


def fail_after(delay: Optional[float], *,
               shield: bool = False) -> 'typing.AsyncContextManager[CancelScope]':
    """
    Create an async context manager which raises an exception if does not finish in time.

    :param delay: maximum allowed time (in seconds) before raising the exception, or ``None`` to
        disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope
    :raises TimeoutError: if the block does not complete within the allotted time

    """
    if delay is None:
        return _get_asynclib().CancelScope(shield=shield)
    else:
        return _get_asynclib().fail_after(delay, shield=shield)


def move_on_after(delay: Optional[float], *,
                  shield: bool = False) -> 'typing.AsyncContextManager[CancelScope]':
    """
    Create an async context manager which is exited if it does not complete within the given time.

    :param delay: maximum allowed time (in seconds) before exiting the context block, or ``None``
        to disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope

    """
    if delay is None:
        return _get_asynclib().CancelScope(shield=shield)
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


def current_time() -> Coroutine[Any, Any, float]:
    """
    Return the current value of the event loop's internal clock.

    :return the clock value (seconds)
    :rtype: float

    """
    return _get_asynclib().current_time()


#
# Task groups
#

def create_task_group() -> TaskGroup:
    """
    Create a task group.

    :return: a task group

    """
    return _get_asynclib().TaskGroup()


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

def aopen(file: Union[str, 'os.PathLike', int], mode: str = 'r', buffering: int = -1,
          encoding: Optional[str] = None, errors: Optional[str] = None,
          newline: Optional[str] = None, closefd: bool = True,
          opener: Optional[Callable] = None) -> Coroutine[Any, Any, AsyncFile]:
    """
    Open a file asynchronously.

    The arguments are exactly the same as for the builtin :func:`open`.

    :return: an asynchronous file object
    :rtype: AsyncFile

    """
    if sys.version_info < (3, 6) and hasattr(file, '__fspath__'):
        file = str(file)

    return _get_asynclib().aopen(file, mode, buffering, encoding, errors, newline, closefd, opener)


#
# Sockets and networking
#

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
    :return: a socket stream object

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


async def connect_unix(path: Union[str, 'os.PathLike']) -> SocketStream:
    """
    Connect to the given UNIX socket.

    Not available on Windows.

    :param path: path to the socket
    :return: a socket stream object

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
    :return: a server object

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
        path: Union[str, 'os.PathLike'], *, mode: Optional[int] = None) -> SocketStreamServer:
    """
    Start a UNIX socket server.

    Not available on Windows.

    :param path: path of the socket
    :param mode: permissions to set on the socket
    :return: a server object

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


def wait_socket_readable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket has data to be read.

    :param sock: a socket object
    :raises anyio.exceptions.ClosedResourceError: if the socket was closed while waiting for the
        socket to become readable
    :raises anyio.exceptions.ResourceBusyError: if another task is already waiting for the socket
        to become readable

    """
    return _get_asynclib().wait_socket_readable(sock)


def wait_socket_writable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket can be written to.

    :param sock: a socket object
    :raises anyio.exceptions.ClosedResourceError: if the socket was closed while waiting for the
        socket to become writable
    :raises anyio.exceptions.ResourceBusyError: if another task is already waiting for the socket
        to become writable

    """
    return _get_asynclib().wait_socket_writable(sock)


def notify_socket_close(sock: socket.SocketType) -> Awaitable[None]:
    """
    Notify any relevant tasks that you are about to close a socket.

    This will cause :exc:`~anyio.exceptions.ClosedResourceError` to be raised on any task waiting
    for the socket to become readable or writable.

    :param sock: the socket to be closed after this

    """
    return _get_asynclib().notify_socket_close(sock)


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

def receive_signals(*signals: int) -> 'typing.AsyncContextManager[typing.AsyncIterator[int]]':
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

class TaskInfo:
    """
    Represents an asynchronous task.

    :ivar int id: the unique identifier of the task
    :ivar parent_id: the identifier of the parent task, if any
    :vartype parent_id: Optional[int]
    :ivar str name: the description of the task (if any)
    :ivar ~collections.abc.Coroutine coro: the coroutine object of the task
    """

    __slots__ = 'id', 'parent_id', 'name', 'coro'

    def __init__(self, id: int, parent_id: Optional[int], name: Optional[str], coro: Coroutine):
        self.id = id
        self.parent_id = parent_id
        self.name = name
        self.coro = coro

    def __eq__(self, other):
        if isinstance(other, TaskInfo):
            return self.id == other.id

        return NotImplemented

    def __hash__(self):
        return hash(self.id)

    def __repr__(self):
        return '{}(id={self.id!r}, name={self.name!r})'.format(self.__class__.__name__, self=self)


async def get_current_task() -> TaskInfo:
    """
    Return the current task.

    :return: a representation of the current task

    """
    return await _get_asynclib().get_current_task()


async def get_running_tasks() -> typing.List[TaskInfo]:
    """
    Return a list of running tasks in the current event loop.

    :return: a list of task info objects

    """
    return await _get_asynclib().get_running_tasks()


async def wait_all_tasks_blocked() -> None:
    """Wait until all other tasks are waiting for something."""
    await _get_asynclib().wait_all_tasks_blocked()
