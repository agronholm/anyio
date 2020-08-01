import math
import os
import socket
import ssl
import sys
import threading
import typing
from contextlib import contextmanager
from importlib import import_module
from ipaddress import ip_address, IPv6Address
from pathlib import Path
from socket import AddressFamily, SocketKind
from subprocess import PIPE, CompletedProcess, DEVNULL, CalledProcessError
from typing import TypeVar, Callable, Union, Optional, Awaitable, Coroutine, Any, Dict, List, Tuple

import sniffio

from ._utils import convert_ipv6_sockaddr
from .abc import (
    Lock, Condition, Event, Semaphore, CapacityLimiter, CancelScope, TaskGroup, IPAddressType,
    SocketStream, UDPSocket, ConnectedUDPSocket, IPSockAddrType, SocketListener, Process,
    AsyncResource)
from .fileio import AsyncFile
from .streams.stapled import MultiListener
from .streams.tls import TLSStream
from .streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

if sys.version_info >= (3, 8):
    from typing import Literal
else:
    from typing_extensions import Literal

BACKENDS = 'asyncio', 'curio', 'trio'
IPPROTO_IPV6 = getattr(socket, 'IPPROTO_IPV6', 41)  # https://bugs.python.org/issue29515

T_Retval = TypeVar('T_Retval', covariant=True)
T_Agen = TypeVar('T_Agen')
T_Item = TypeVar('T_Item')
GetAddrInfoReturnType = List[Tuple[AddressFamily, SocketKind, int, str, Tuple[str, int]]]
AnyIPAddressFamily = Literal[AddressFamily.AF_UNSPEC, AddressFamily.AF_INET,
                             AddressFamily.AF_INET6]
IPAddressFamily = Literal[AddressFamily.AF_INET, AddressFamily.AF_INET6]
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
        raise RuntimeError(f'Already running {asynclib_name} in this thread')

    try:
        asynclib = import_module(f'{__name__}._backends._{backend}')
    except ImportError as exc:
        raise LookupError(f'No such backend: {backend}') from exc

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


def _get_asynclib(asynclib_name: Optional[str] = None):
    if asynclib_name is None:
        asynclib_name = sniffio.current_async_library()

    modulename = 'anyio._backends._' + asynclib_name
    try:
        return sys.modules[modulename]
    except KeyError:
        return import_module(modulename)


#
# Miscellaneous
#

def sleep(delay: float) -> Coroutine[Any, Any, None]:
    """
    Pause the current task for the specified duration.

    :param delay: the duration, in seconds

    """
    return _get_asynclib().sleep(delay)


def get_cancelled_exc_class() -> typing.Type[BaseException]:
    """Return the current async library's cancellation exception class."""
    return _get_asynclib().CancelledError


async def aclose_forcefully(resource: AsyncResource) -> None:
    """
    Close an asynchronous resource in a cancelled scope.

    Doing this closes the resource without waiting on anything.

    :param resource: the resource to close

    """
    async with open_cancel_scope() as scope:
        await scope.cancel()
        await resource.aclose()


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

def run_sync_in_worker_thread(func: Callable[..., T_Retval], *args, cancellable: bool = False,
                              limiter: Optional[CapacityLimiter] = None) -> Awaitable[T_Retval]:
    """
    Start a thread that calls the given function with the given arguments.

    If the ``cancellable`` option is enabled and the task waiting for its completion is cancelled,
    the thread will still run its course but its return value (or any raised exception) will be
    ignored.

    :param func: a callable
    :param args: positional arguments for the callable
    :param cancellable: ``True`` to allow cancellation of the operation
    :param limiter: capacity limiter to use to limit the total amount of threads running
        (if omitted, the default limiter is used)
    :return: an awaitable that yields the return value of the function.

    """
    return _get_asynclib().run_sync_in_worker_thread(func, *args, cancellable=cancellable,
                                                     limiter=limiter)


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


def current_default_worker_thread_limiter() -> CapacityLimiter:
    """
    Return the capacity limiter that is used by default to limit the number of concurrent threads.

    :return: a capacity limiter object

    """
    return _get_asynclib().current_default_thread_limiter()


#
# Subprocesses
#

async def run_process(command: Union[str, typing.Sequence[str]], *, input: Optional[bytes] = None,
                      stdout: int = PIPE, stderr: int = PIPE,
                      check: bool = True) -> CompletedProcess:
    """
    Run an external command in a subprocess and wait until it completes.

    .. seealso:: :func:`subprocess.run`

    :param command: either a string to pass to the shell, or an iterable of strings containing the
        executable name or path and its arguments
    :param input: bytes passed to the standard input of the subprocess
    :param stdout: either :data:`subprocess.PIPE` or :data:`subprocess.DEVNULL`
    :param stderr: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL` or
        :data:`subprocess.STDOUT`
    :param check: if ``True``, raise :exc:`~subprocess.CalledProcessError` if the process
        terminates with a return code other than 0
    :return: an object representing the completed process
    :raises CalledProcessError: if ``check`` is ``True`` and the process exits with a nonzero
        return code

    """
    async def drain_stream(stream, index):
        chunks = [chunk async for chunk in stream]
        stream_contents[index] = b''.join(chunks)

    async with await open_process(command, stdin=PIPE if input else DEVNULL, stdout=stdout,
                                  stderr=stderr) as process:
        stream_contents = [None, None]
        try:
            async with create_task_group() as tg:
                if process.stdout:
                    await tg.spawn(drain_stream, process.stdout, 0)
                if process.stderr:
                    await tg.spawn(drain_stream, process.stderr, 1)
                if process.stdin and input:
                    await process.stdin.send(input)
                    await process.stdin.aclose()

                await process.wait()
        except BaseException:
            process.kill()
            raise

    output, errors = stream_contents
    if check and process.returncode != 0:
        raise CalledProcessError(typing.cast(int, process.returncode), command, output, errors)

    return CompletedProcess(command, typing.cast(int, process.returncode), output, errors)


async def open_process(command: Union[str, typing.Sequence[str]], *, stdin: int = PIPE,
                       stdout: int = PIPE, stderr: int = PIPE) -> Process:
    """
    Start an external command in a subprocess.

    .. seealso:: :class:`subprocess.Popen`

    :param command: either a string to pass to the shell, or an iterable of strings containing the
        executable name or path and its arguments
    :param stdin: either :data:`subprocess.PIPE` or :data:`subprocess.DEVNULL`
    :param stdout: either :data:`subprocess.PIPE` or :data:`subprocess.DEVNULL`
    :param stderr: one of :data:`subprocess.PIPE`, :data:`subprocess.DEVNULL` or
        :data:`subprocess.STDOUT`
    :return: an asynchronous process object

    """
    shell = isinstance(command, str)
    return await _get_asynclib().open_process(command, shell=shell, stdin=stdin, stdout=stdout,
                                              stderr=stderr)


#
# Async file I/O
#

async def open_file(file: Union[str, 'os.PathLike', int], mode: str = 'r', buffering: int = -1,
                    encoding: Optional[str] = None, errors: Optional[str] = None,
                    newline: Optional[str] = None, closefd: bool = True,
                    opener: Optional[Callable] = None) -> AsyncFile:
    """
    Open a file asynchronously.

    The arguments are exactly the same as for the builtin :func:`open`.

    :return: an asynchronous file object

    """
    fp = await run_sync_in_worker_thread(open, file, mode, buffering, encoding, errors, newline,
                                         closefd, opener)
    return AsyncFile(fp)


#
# Sockets and networking
#

async def connect_tcp(
    remote_host: IPAddressType, remote_port: int, *, local_host: Optional[IPAddressType] = None,
    local_port: Optional[int] = None, happy_eyeballs_delay: float = 0.25
) -> SocketStream:
    """
    Connect to a host using the TCP protocol.

    This function implements the stateless version of the Happy Eyeballs algorithm (RFC 6555).
    If ``address`` is a host name that resolves to multiple IP addresses, each one is tried until
    one connection attempt succeeds. If the first attempt does not connected within 250
    milliseconds, a second attempt is started using the next address in the list, and so on.
    For IPv6 enabled systems, IPv6 addresses are tried first.

    :param remote_host: the IP address or host name to connect to
    :param remote_port: port on the target host to connect to
    :param local_host: the interface address or name to bind the socket to before connecting
    :param local_port: the port to bind the socket to before connecting
    :param happy_eyeballs_delay: delay (in seconds) before starting the next connection attempt
    :return: a socket stream object
    :raises OSError: if the connection attempt fails

    """
    # Placed here due to https://github.com/python/mypy/issues/7057
    connected_stream: Optional[SocketStream] = None

    async def try_connect(remote_host: str, event: Event):
        nonlocal connected_stream
        try:
            stream = await asynclib.connect_tcp(remote_host, remote_port, local_address)
        except OSError as exc:
            oserrors.append(exc)
            return
        else:
            if connected_stream is None:
                connected_stream = stream
                await tg.cancel_scope.cancel()
            else:
                await stream.aclose()
        finally:
            await event.set()

    asynclib = _get_asynclib()
    local_address: Optional[IPSockAddrType] = None
    family = socket.AF_UNSPEC
    if local_host:
        gai_res = await getaddrinfo(str(local_host), local_port)
        family, *_, local_address = gai_res[0]

    target_host = str(remote_host)
    try:
        addr_obj = ip_address(remote_host)
    except ValueError:
        # getaddrinfo() will raise an exception if name resolution fails
        gai_res = await getaddrinfo(target_host, remote_port, family=family,
                                    type=socket.SOCK_STREAM)

        # Organize the list so that the first address is an IPv6 address (if available) and the
        # second one is an IPv4 addresses. The rest can be in whatever order.
        v6_found = v4_found = False
        target_addrs: List[Tuple[socket.AddressFamily, str]] = []
        for af, *rest, sa in gai_res:
            if af == socket.AF_INET6 and not v6_found:
                v6_found = True
                target_addrs.insert(0, (af, sa[0]))
            elif af == socket.AF_INET and not v4_found and v6_found:
                v4_found = True
                target_addrs.insert(1, (af, sa[0]))
            else:
                target_addrs.append((af, sa[0]))
    else:
        if isinstance(addr_obj, IPv6Address):
            target_addrs = [(socket.AF_INET6, addr_obj.compressed)]
        else:
            target_addrs = [(socket.AF_INET, addr_obj.compressed)]

    oserrors: List[OSError] = []
    async with create_task_group() as tg:
        for i, (af, addr) in enumerate(target_addrs):
            event = create_event()
            await tg.spawn(try_connect, addr, event)
            async with move_on_after(happy_eyeballs_delay):
                await event.wait()

    if connected_stream is None:
        cause = oserrors[0] if len(oserrors) == 1 else asynclib.ExceptionGroup(oserrors)
        raise OSError('All connection attempts failed') from cause

    return connected_stream


async def connect_tcp_with_tls(
    remote_host: IPAddressType, remote_port: int, *, local_host: Optional[IPAddressType] = None,
    local_port: Optional[int] = None, happy_eyeballs_delay: float = 0.25,
    server_hostname: Optional[str] = None, ssl_context: Optional[ssl.SSLContext] = None
) -> TLSStream:
    """
    Connect to a host using TCP and establish a TLS encrypted session over it.

    This is a shortcut to first  :func:`connect_tcp` and then wrapping it using
    :meth:`~anyio.streams.tls.TLSStream.wrap`.

    :param remote_host: the IP address or host name to connect to
    :param remote_port: port on the target host to connect to
    :param local_host: the interface address or name to bind the socket to before connecting
    :param local_port: the port to bind the socket to before connecting
    :param happy_eyeballs_delay: delay (in seconds) before starting the next connection attempt
    :param server_hostname: host name to use for checking against the server certificate
        (defaults to the value of ``remote_host``)
    :param ssl_context: the SSL context object to use (if omitted, a default context is created)
    :return: a socket stream object
    :raises OSError: if the connection attempt fails
    :raises ssl.SSLError: if the TLS handshake fails

    """
    stream = await connect_tcp(remote_host, remote_port, local_host=local_host,
                               local_port=local_port, happy_eyeballs_delay=happy_eyeballs_delay)
    hostname = server_hostname or str(remote_host)
    return await TLSStream.wrap(stream, server_side=False, hostname=hostname,
                                ssl_context=ssl_context)


async def connect_unix(path: Union[str, 'os.PathLike']) -> SocketStream:
    """
    Connect to the given UNIX socket.

    Not available on Windows.

    :param path: path to the socket
    :return: a socket stream object

    """
    path = str(Path(path))
    return await _get_asynclib().connect_unix(path)


async def create_tcp_listener(
    *, local_host: Optional[IPAddressType] = None, local_port: int = 0,
    family: AnyIPAddressFamily = socket.AddressFamily.AF_UNSPEC, backlog: int = 65536,
    reuse_port: bool = False
) -> MultiListener[SocketStream[IPSockAddrType]]:
    """
    Create a TCP socket listener.

    :param local_port: port number to listen on
    :param local_host: IP address of the interface to listen on. If omitted, listen on all IPv4
        and IPv6 interfaces. To listen on all interfaces on a specific address family, use
        ``0.0.0.0`` for IPv4 or ``::`` for IPv6.
    :param family: address family (used if ``interface`` was omitted)
    :param backlog: maximum number of queued incoming connections (up to a maximum of 2**16, or
        65536)
    :param reuse_port: ``True`` to allow multiple sockets to bind to the same address/port
        (not supported on Windows)
    :return: a list of listener objects

    """
    asynclib = _get_asynclib()
    backlog = min(backlog, 65536)
    local_host = str(local_host) if local_host is not None else None
    gai_res = await getaddrinfo(local_host, local_port, family=family,  # type: ignore[arg-type]
                                type=socket.SOCK_STREAM,
                                flags=socket.AI_PASSIVE | socket.AI_ADDRCONFIG)
    listeners: List[SocketListener[IPSockAddrType]] = []
    try:
        # The set() is here to work around a glibc bug:
        # https://sourceware.org/bugzilla/show_bug.cgi?id=14969
        for fam, *_, sockaddr in sorted(set(gai_res)):
            raw_socket = socket.socket(fam)
            raw_socket.setblocking(False)

            # For Windows, enable exclusive address use. For others, enable address reuse.
            if sys.platform == 'win32':
                raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
            else:
                raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)

            if reuse_port:
                raw_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

            # If only IPv6 was requested, disable dual stack operation
            if fam == socket.AF_INET6:
                raw_socket.setsockopt(IPPROTO_IPV6, socket.IPV6_V6ONLY, 1)

            raw_socket.bind(sockaddr)
            raw_socket.listen(backlog)
            listener = asynclib.SocketListener(raw_socket)
            listeners.append(listener)
    except BaseException:
        for listener in listeners:
            await listener.aclose()

        raise

    return MultiListener(listeners)


async def create_unix_listener(
        path: Union[str, 'os.PathLike'], *, mode: Optional[int] = None,
        backlog: int = 65536) -> SocketListener[str]:
    """
    Create a UNIX socket listener.

    Not available on Windows.

    :param path: path of the socket
    :param mode: permissions to set on the socket
    :param backlog: maximum number of queued incoming connections (up to a maximum of 2**16, or
        65536)
    :return: a listener object

    """
    path = str(Path(path))
    backlog = min(backlog, 65536)
    raw_socket = socket.socket(socket.AF_UNIX)
    raw_socket.setblocking(False)
    try:
        await run_sync_in_worker_thread(raw_socket.bind, path, cancellable=True)
        if mode is not None:
            await run_sync_in_worker_thread(os.chmod, path, mode, cancellable=True)

        raw_socket.listen(backlog)
        return _get_asynclib().SocketListener(raw_socket)
    except BaseException:
        raw_socket.close()
        raise


async def create_udp_socket(
    family: AnyIPAddressFamily = AddressFamily.AF_UNSPEC, *,
    local_host: Optional[IPAddressType] = None, local_port: int = 0, reuse_port: bool = False
) -> UDPSocket:
    """
    Create a UDP socket.

    If ``port`` has been given, the socket will be bound to this port on the local machine,
    making this socket suitable for providing UDP based services.

    :param family: address family (``AF_INET`` or ``AF_INET6``) – automatically determined from
        ``interface`` or ``target_host`` if omitted
    :param local_host: IP address or host name of the local interface to bind to
    :param local_port: local port to bind to
    :param reuse_port: ``True`` to allow multiple sockets to bind to the same address/port
        (not supported on Windows)
    :return: a UDP socket

    """
    if family is AddressFamily.AF_UNSPEC and not local_host:
        raise ValueError('Either "family" or "local_host" must be given')

    local_address: Optional[IPSockAddrType] = None
    if local_host:
        gai_res = await getaddrinfo(str(local_host), local_port, family=family,
                                    type=socket.SOCK_DGRAM,
                                    flags=socket.AI_PASSIVE | socket.AI_ADDRCONFIG)
        family = typing.cast(AnyIPAddressFamily, gai_res[0][0])
        local_address = gai_res[0][-1]

    return await _get_asynclib().create_udp_socket(family, local_address, None, reuse_port)


async def create_connected_udp_socket(
    remote_host: IPAddressType, remote_port: int, *,
    family: AnyIPAddressFamily = AddressFamily.AF_UNSPEC,
    local_host: Optional[IPAddressType] = None, local_port: int = 0, reuse_port: bool = False
) -> ConnectedUDPSocket:
    """
    Create a connected UDP socket.

    Connected UDP sockets can only communicate with the specified remote host/port, and any packets
    sent from other sources are dropped.

    :param remote_host: remote host to set as the default target
    :param remote_port: port on the remote host to set as the default target
    :param family: address family (``AF_INET`` or ``AF_INET6``) – automatically determined from
        ``local_host`` or ``remote_host`` if omitted
    :param local_host: IP address or host name of the local interface to bind to
    :param local_port: local port to bind to
    :param reuse_port: ``True`` to allow multiple sockets to bind to the same address/port
        (not supported on Windows)
    :return: a connected UDP socket

    """
    local_address = None
    if local_host:
        gai_res = await getaddrinfo(str(local_host), local_port, family=family,
                                    type=socket.SOCK_DGRAM,
                                    flags=socket.AI_PASSIVE | socket.AI_ADDRCONFIG)
        family = typing.cast(AnyIPAddressFamily, gai_res[0][0])
        local_address = gai_res[0][-1]

    gai_res = await getaddrinfo(str(remote_host), remote_port, family=family,
                                type=socket.SOCK_DGRAM)
    family = typing.cast(AnyIPAddressFamily, gai_res[0][0])
    remote_address = gai_res[0][-1]

    return await _get_asynclib().create_udp_socket(family, local_address, remote_address,
                                                   reuse_port)


async def getaddrinfo(host: Union[bytearray, bytes, str], port: Union[str, int, None], *,
                      family: Union[int, AddressFamily] = 0, type: Union[int, SocketKind] = 0,
                      proto: int = 0, flags: int = 0) -> GetAddrInfoReturnType:
    """
    Look up a numeric IP address given a host name.

    Internationalized domain names are translated according to the (non-transitional) IDNA 2008
    standard.

    .. note:: 4-tuple IPv6 socket addresses are automatically converted to 2-tuples of
        (host, port), unlike what :func:`socket.getaddrinfo` does.

    :param host: host name
    :param port: port number
    :param family: socket family (`'AF_INET``, ...)
    :param type: socket type (``SOCK_STREAM``, ...)
    :param proto: protocol number
    :param flags: flags to pass to upstream ``getaddrinfo()``
    :return: list of tuples containing (family, type, proto, canonname, sockaddr)

    .. seealso:: :func:`socket.getaddrinfo`

    """
    # Handle unicode hostnames
    if isinstance(host, str):
        try:
            encoded_host = host.encode('ascii')
        except UnicodeEncodeError:
            import idna
            encoded_host = idna.encode(host, uts46=True)
    else:
        encoded_host = host

    gai_res = await _get_asynclib().getaddrinfo(encoded_host, port, family=family, type=type,
                                                proto=proto, flags=flags)
    return [(family, type, proto, canonname, convert_ipv6_sockaddr(sockaddr))
            for family, type, proto, canonname, sockaddr in gai_res]


def getnameinfo(sockaddr: IPSockAddrType, flags: int = 0) -> Awaitable[Tuple[str, str]]:
    """
    Look up the host name of an IP address.

    :param sockaddr: socket address (e.g. (ipaddress, port) for IPv4)
    :param flags: flags to pass to upstream ``getnameinfo()``
    :return: a tuple of (host name, service name)

    .. seealso:: :func:`socket.getnameinfo`

    """
    return _get_asynclib().getnameinfo(sockaddr, flags)


def wait_socket_readable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket has data to be read.

    This does **NOT** work on Windows when using the asyncio backend with a proactor event loop
    (default on py3.8+).

    :param sock: a socket object
    :raises anyio.exceptions.ClosedResourceError: if the socket was closed while waiting for the
        socket to become readable
    :raises anyio.exceptions.BusyResourceError: if another task is already waiting for the socket
        to become readable

    """
    return _get_asynclib().wait_socket_readable(sock)


def wait_socket_writable(sock: Union[socket.SocketType, ssl.SSLSocket]) -> Awaitable[None]:
    """
    Wait until the given socket can be written to.

    This does **NOT** work on Windows when using the asyncio backend with a proactor event loop
    (default on py3.8+).

    :param sock: a socket object
    :raises anyio.exceptions.ClosedResourceError: if the socket was closed while waiting for the
        socket to become writable
    :raises anyio.exceptions.BusyResourceError: if another task is already waiting for the socket
        to become writable

    """
    return _get_asynclib().wait_socket_writable(sock)


#
# Synchronization
#

def create_lock() -> Lock:
    """
    Create an asynchronous lock.

    :return: a lock object

    """
    return _get_asynclib().Lock()


def create_condition(lock: Lock = None) -> Condition:
    """
    Create an asynchronous condition.

    :param lock: the lock to base the condition object on
    :return: a condition object

    """
    return _get_asynclib().Condition(lock=lock)


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


def create_capacity_limiter(total_tokens: float) -> CapacityLimiter:
    """
    Create a capacity limiter.

    :param total_tokens: the total number of tokens available for borrowing (can be an integer or
        :data:`math.inf`)
    :return: a capacity limiter object

    """
    return _get_asynclib().CapacityLimiter(total_tokens)


@typing.overload
def create_memory_object_stream(
    max_buffer_size: float, item_type: typing.Type[T_Item]
) -> Tuple['MemoryObjectSendStream[T_Item]', 'MemoryObjectReceiveStream[T_Item]']:
    ...


@typing.overload
def create_memory_object_stream(
    max_buffer_size: float = 0
) -> Tuple['MemoryObjectSendStream[Any]', 'MemoryObjectReceiveStream[Any]']:
    ...


def create_memory_object_stream(max_buffer_size=0, item_type=None):
    """
    Create a memory object stream.

    :param max_buffer_size: number of items held in the buffer until ``send()`` starts blocking
    :param item_type: type of item, for marking the streams with the right generic type for
        static typing (not used at run time)
    :return: a tuple of (send stream, receive stream)

    """
    from .streams.memory import (
        _MemoryObjectStreamState, MemoryObjectSendStream, MemoryObjectReceiveStream)

    if max_buffer_size != math.inf and not isinstance(max_buffer_size, int):
        raise ValueError('max_buffer_size must be either an integer or math.inf')
    if max_buffer_size < 0:
        raise ValueError('max_buffer_size cannot be negative')

    state: _MemoryObjectStreamState = _MemoryObjectStreamState(max_buffer_size)
    return MemoryObjectSendStream(state), MemoryObjectReceiveStream(state)


#
# Operating system signals
#

def open_signal_receiver(*signals: int) -> 'typing.AsyncContextManager[typing.AsyncIterator[int]]':
    """
    Start receiving operating system signals.

    :param signals: signals to receive (e.g. ``signal.SIGINT``)
    :return: an asynchronous context manager for an asynchronous iterator which yields signal
        numbers

    .. warning:: Windows does not support signals natively so it is best to avoid relying on this
        in cross-platform applications.

    """
    return _get_asynclib().open_signal_receiver(*signals)


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
        return f'{self.__class__.__name__}(id={self.id!r}, name={self.name!r})'


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
