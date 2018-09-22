import errno
import os
import socket
import ssl
import sys
from functools import wraps
from ipaddress import ip_address
from ssl import SSLContext
from typing import Callable, Union, Optional, Tuple, Any

import trio.hazmat
from async_generator import async_generator, yield_, asynccontextmanager

from hyperio.interfaces import BufferType
from ..exceptions import ExceptionGroup, DelimiterNotFound
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
        raise ExceptionGroup(exc.exceptions) from None


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

class TrioSocket:
    __slots__ = '_raw_socket'

    def __init__(self, raw_socket) -> None:
        self._raw_socket = raw_socket
        self._raw_socket.setblocking(False)

    def __getattr__(self, item):
        return getattr(self._raw_socket, item)

    async def accept(self):
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            raw_socket, address = self._raw_socket.accept()
        except BlockingIOError:
            await trio.hazmat.wait_socket_readable(self._raw_socket)
            raw_socket, address = self._raw_socket.accept()

        return TrioSocket(raw_socket), address

    async def bind(self, address: Union[Tuple[str, int], str]) -> None:
        await trio.hazmat.checkpoint_if_cancelled()
        if isinstance(address, tuple) and len(address) == 2:
            # For IP address/port combinations, call bind() directly
            try:
                ip_address(address[0])
            except ValueError:
                pass
            else:
                self._raw_socket.bind(address)
                return

        # In all other cases, do this in a worker thread to avoid blocking the event loop thread
        await run_in_thread(self._raw_socket.bind, address)

    async def connect(self, address: Union[tuple, str, bytes]) -> None:
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            self._raw_socket.connect(address)
        except BlockingIOError:
            await trio.hazmat.wait_socket_writable(self._raw_socket)

        error = self._raw_socket.getsockopt(socket.SOL_SOCKET, socket.SO_ERROR)
        if error:
            raise OSError(error, errno.errorcode[error])

    async def recv(self, size: int, *, flags: int = 0) -> bytes:
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            return self._raw_socket.recv(size, flags)
        except (BlockingIOError, ssl.SSLWantReadError):
            await trio.hazmat.wait_socket_readable(self._raw_socket)
            return self._raw_socket.recv(size, flags)

    async def recvfrom(self, size: int, *, flags: int = 0) -> Tuple[bytes, Any]:
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            return self._raw_socket.recvfrom(size, flags)
        except BlockingIOError:
            await trio.hazmat.wait_socket_readable(self._raw_socket)
            return self._raw_socket.recvfrom(size, flags)

    async def recv_into(self, buffer, nbytes: int, *, flags: int = 0) -> int:
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            return self._raw_socket.recv_into(buffer, nbytes, flags)
        except (BlockingIOError, ssl.SSLWantReadError):
            await trio.hazmat.wait_socket_readable(self._raw_socket)
            return self._raw_socket.recv_into(buffer, nbytes, flags)

    async def send(self, data: bytes, *, flags: int = 0) -> int:
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            return self._raw_socket.send(data, flags)
        except (BlockingIOError, ssl.SSLWantWriteError):
            await trio.hazmat.wait_socket_writable(self._raw_socket)
            return self._raw_socket.send(data, flags)

    async def sendto(self, data: bytes, addr, *, flags: int = 0) -> int:
        await trio.hazmat.checkpoint_if_cancelled()
        try:
            return self._raw_socket.sendto(data, flags, addr)
        except BlockingIOError:
            await trio.hazmat.wait_socket_writable(self._raw_socket)
            return self._raw_socket.sendto(data, flags, addr)

    async def sendall(self, data: bytes, *, flags: int = 0) -> None:
        await trio.hazmat.checkpoint_if_cancelled()
        to_send = len(data)
        while to_send > 0:
            try:
                sent = self._raw_socket.send(data, flags)
            except (BlockingIOError, ssl.SSLWantWriteError):
                await trio.hazmat.wait_socket_writable(self._raw_socket)
            else:
                to_send -= sent

    async def start_tls(self, context: SSLContext, server_hostname: Optional[str] = None) -> None:
        plain_socket = self._raw_socket
        self._raw_socket = context.wrap_socket(
            self._raw_socket, server_side=not server_hostname, do_handshake_on_connect=False,
            server_hostname=server_hostname)
        while True:
            try:
                self._raw_socket.do_handshake()
            except ssl.SSLWantReadError:
                await trio.hazmat.wait_socket_readable(self._raw_socket)
            except ssl.SSLWantWriteError:
                await trio.hazmat.wait_socket_writable(self._raw_socket)
            except BaseException:
                self._raw_socket = plain_socket
                raise
            else:
                break


class SocketStream(interfaces.SocketStream):
    __slots__ = '_socket', '_ssl_context', '_server_hostname'

    def __init__(self, sock: TrioSocket, ssl_context: Optional[SSLContext] = None,
                 server_hostname: Optional[str] = None) -> None:
        self._socket = sock
        self._ssl_context = ssl_context
        self._server_hostname = server_hostname

    async def receive_some(self, max_bytes: Optional[int]) -> bytes:
        return await self._socket.recv(max_bytes)

    async def receive_exactly(self, nbytes: int) -> bytes:
        buf = bytearray(nbytes)
        view = memoryview(buf)
        while nbytes > 0:
            bytes_read = await self._socket.recv_into(view, nbytes)
            view = view[bytes_read:]
            nbytes -= bytes_read

        return bytes(buf)

    async def receive_until(self, delimiter: bytes, max_size: int) -> bytes:
        offset = 0
        delimiter_size = len(delimiter)
        buf = b''
        while len(buf) < max_size:
            read_size = max_size - len(buf)
            data = await self._socket.recv(read_size, flags=socket.MSG_PEEK)
            buf += data
            index = buf.find(delimiter, offset)
            if index >= 0:
                await self._socket.recv(index + 1)
                return buf[:index]
            else:
                await self._socket.recv(len(data))
                offset += len(data) - delimiter_size + 1

        raise DelimiterNotFound(buf, False)

    async def send_all(self, data: BufferType) -> None:
        to_send = len(data)
        while to_send > 0:
            to_send -= await self._socket.send(data)

    async def start_tls(self, context: Optional[SSLContext] = None) -> None:
        ssl_context = context or self._ssl_context or ssl.create_default_context()
        await self._socket.start_tls(ssl_context, self._server_hostname)


class SocketStreamServer(interfaces.SocketStreamServer):
    __slots__ = '_socket', '_ssl_context'

    def __init__(self, sock: TrioSocket, ssl_context: Optional[SSLContext]) -> None:
        self._socket = sock
        self._ssl_context = ssl_context

    @property
    def address(self) -> Union[tuple, str]:
        return self._socket.getsockname()

    @asynccontextmanager
    @async_generator
    async def accept(self):
        sock, addr = await self._socket.accept()
        stream = SocketStream(sock)
        if self._ssl_context:
            await stream.start_tls(self._ssl_context)

        await yield_(stream)
        sock.close()


class DatagramSocket(interfaces.DatagramSocket):
    __slots__ = '_socket'

    def __init__(self, sock: TrioSocket) -> None:
        self._socket = sock

    async def receive(self, max_bytes: int) -> Tuple[bytes, str]:
        return await self._socket.recvfrom(max_bytes)

    async def send(self, data: bytes, address: Optional[str] = None,
                   port: Optional[int] = None) -> None:
        if address is not None and port is not None:
            await self._socket.sendto(data, str(address))
        else:
            await self._socket.send(data)


def create_socket(family: int = socket.AF_INET, type: int = socket.SOCK_STREAM,
                  proto: int = 0, fileno=None):
    raw_socket = socket.socket(family, type, proto, fileno)
    return TrioSocket(raw_socket)


@asynccontextmanager
@async_generator
async def connect_tcp(
        address: str, port: int, *, tls: Union[bool, SSLContext] = False,
        bind_host: Optional[str] = None, bind_port: Optional[int] = None):
    sock = create_socket()
    try:
        if bind_host is not None and bind_port is not None:
            await sock.bind((bind_host, bind_port))

        await sock.connect((address, port))
        stream = SocketStream(sock, server_hostname=address)

        if isinstance(tls, SSLContext):
            await stream.start_tls(tls)
        elif tls:
            await stream.start_tls()

        await yield_(stream)
    finally:
        sock.close()


@asynccontextmanager
@async_generator
async def connect_unix(path: str):
    sock = create_socket(socket.AF_UNIX)
    try:
        await sock.connect(path)
        await yield_(SocketStream(sock))
    finally:
        sock.close()


@asynccontextmanager
@async_generator
async def create_tcp_server(port: int, interface: Optional[str], *,
                            ssl_context: Optional[SSLContext] = None):
    sock = create_socket()
    try:
        await sock.bind((interface, port))
        sock.listen()
        await yield_(SocketStreamServer(sock, ssl_context))
    finally:
        sock.close()


@asynccontextmanager
@async_generator
async def create_unix_server(path: str, *, mode: Optional[int] = None):
    sock = create_socket(socket.AF_UNIX)
    try:
        await sock.bind(path)

        if mode is not None:
            os.chmod(path, mode)

        sock.listen()
        await yield_(SocketStreamServer(sock, None))
    finally:
        sock.close()


@asynccontextmanager
@async_generator
async def create_udp_socket(
        *, bind_host: Optional[str] = None, bind_port: Optional[int] = None,
        target_host: Optional[str] = None, target_port: Optional[int] = None):
    sock = create_socket(type=socket.SOCK_DGRAM)
    try:
        if bind_port is not None:
            await sock.bind((bind_host, bind_port))

        if target_host is not None and target_port is not None:
            await sock.connect((target_host, target_port))

        await yield_(DatagramSocket(sock))
    finally:
        sock.close()


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
interfaces.Lock.register(Lock)
interfaces.Condition.register(Condition)
interfaces.Event.register(Event)
interfaces.Semaphore.register(Semaphore)
interfaces.Queue.register(Queue)
