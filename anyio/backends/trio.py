import os
import socket
import ssl
import sys
from functools import wraps
from ssl import SSLContext
from typing import Callable, Union, Optional, Tuple

import trio.hazmat
from async_generator import async_generator, yield_, asynccontextmanager

from .base import BaseSocket
from ..exceptions import ExceptionGroup, DelimiterNotFound
from .. import abc, claim_current_thread, T_Retval, BufferType, _local


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
async def create_task_group():
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
# Async file I/O
#

aopen = trio.open_file


#
# Networking
#

class TrioSocket(BaseSocket):
    __slots__ = ()

    def _wait_readable(self):
        return wait_socket_readable(self._raw_socket)

    def _wait_writable(self) -> None:
        return wait_socket_writable(self._raw_socket)

    def _check_cancelled(self) -> None:
        return trio.hazmat.checkpoint_if_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


class SocketStream(abc.SocketStream):
    __slots__ = '_socket', '_ssl_context', '_server_hostname'

    def __init__(self, sock: TrioSocket, ssl_context: Optional[SSLContext] = None,
                 server_hostname: Optional[str] = None) -> None:
        self._socket = sock
        self._ssl_context = ssl_context
        self._server_hostname = server_hostname

    def close(self):
        self._socket.close()

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


class SocketStreamServer(abc.SocketStreamServer):
    __slots__ = '_socket', '_ssl_context'

    def __init__(self, sock: TrioSocket, ssl_context: Optional[SSLContext]) -> None:
        self._socket = sock
        self._ssl_context = ssl_context

    def close(self) -> None:
        self._socket.close()

    @property
    def address(self) -> Union[tuple, str]:
        return self._socket.getsockname()

    async def accept(self):
        sock, addr = await self._socket.accept()
        try:
            stream = SocketStream(sock)
            if self._ssl_context:
                await stream.start_tls(self._ssl_context)

            return stream
        except BaseException:
            sock.close()
            raise


class DatagramSocket(abc.DatagramSocket):
    __slots__ = '_socket'

    def __init__(self, sock: TrioSocket) -> None:
        self._socket = sock

    def close(self):
        self._socket.close()

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

        return stream
    except BaseException:
        sock.close()
        raise


async def connect_unix(path: str):
    sock = create_socket(socket.AF_UNIX)
    try:
        await sock.connect(path)
        return SocketStream(sock)
    except BaseException:
        sock.close()
        raise


async def create_tcp_server(port: int, interface: Optional[str], *,
                            ssl_context: Optional[SSLContext] = None):
    sock = create_socket()
    try:
        await sock.bind((interface, port))
        sock.listen()
        return SocketStreamServer(sock, ssl_context)
    except BaseException:
        sock.close()
        raise


async def create_unix_server(path: str, *, mode: Optional[int] = None):
    sock = create_socket(socket.AF_UNIX)
    try:
        await sock.bind(path)

        if mode is not None:
            os.chmod(path, mode)

        sock.listen()
        return SocketStreamServer(sock, None)
    except BaseException:
        sock.close()
        raise


async def create_udp_socket(
        *, bind_host: Optional[str] = None, bind_port: Optional[int] = None,
        target_host: Optional[str] = None, target_port: Optional[int] = None):
    sock = create_socket(type=socket.SOCK_DGRAM)
    try:
        if bind_port is not None:
            await sock.bind((bind_host, bind_port))

        if target_host is not None and target_port is not None:
            await sock.connect((target_host, target_port))

        return DatagramSocket(sock)
    except BaseException:
        sock.close()
        raise


#
# Signal handling
#

@asynccontextmanager
@async_generator
async def receive_signals(*signals: int):
    with trio.open_signal_receiver(*signals) as cm:
        await yield_(cm)


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
wait_socket_readable = trio.hazmat.wait_socket_readable
wait_socket_writable = trio.hazmat.wait_socket_writable

Lock = trio.Lock
Semaphore = trio.Semaphore
Queue = trio.Queue

abc.TaskGroup.register(TaskGroup)
abc.Lock.register(Lock)
abc.Condition.register(Condition)
abc.Event.register(Event)
abc.Semaphore.register(Semaphore)
abc.Queue.register(Queue)
