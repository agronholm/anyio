import os
import socket
import ssl
import sys
from contextlib import contextmanager
from functools import partial
from ssl import SSLContext
from typing import Callable, Set, List, Optional, Union, Tuple, Awaitable  # noqa: F401

import curio.io
import curio.socket
import curio.ssl
import curio.traps
from async_generator import async_generator, asynccontextmanager, yield_

from anyio import IPAddressType
from .base import BaseSocket
from .. import abc, T_Retval, BufferType, claim_current_thread, _local
from ..exceptions import ExceptionGroup, CancelledError, DelimiterNotFound


def run(func: Callable[..., T_Retval], *args) -> T_Retval:
    kernel = None
    try:
        with curio.Kernel() as kernel:
            return kernel.run(func, *args)
    except BaseException:
        if kernel:
            kernel.run(shutdown=True)

        raise


@contextmanager
def translate_exceptions():
    try:
        yield
    except (curio.CancelledError, curio.TaskCancelled) as exc:
        raise CancelledError().with_traceback(exc.__traceback__) from None


#
# Timeouts and cancellation
#

class CurioCancelScope(abc.CancelScope):
    __slots__ = 'children', '_tasks', '_cancel_called'

    def __init__(self) -> None:
        self.children = set()  # type: Set[CurioCancelScope]
        self._tasks = set()  # type: Set[curio.Task]
        self._cancel_called = False

    def add_task(self, task: curio.Task) -> None:
        self._tasks.add(task)

    def remove_task(self, task: curio.Task) -> None:
        self._tasks.remove(task)

    async def cancel(self):
        if not self._cancel_called:
            self._cancel_called = True

            for task in self._tasks:
                if task.coro.cr_await is not None:
                    await task.cancel(blocking=False)

            for scope in self.children:
                await scope.cancel()


def get_cancel_scope(task: curio.Task) -> Optional[CurioCancelScope]:
    try:
        return _local.cancel_scopes_by_task.get(task)
    except AttributeError:
        return None


def set_cancel_scope(task: curio.Task, scope: Optional[CurioCancelScope]) -> None:
    try:
        cancel_scopes = _local.cancel_scopes_by_task
    except AttributeError:
        cancel_scopes = _local.cancel_scopes_by_task = {}

    if scope is None:
        del cancel_scopes[task]
    else:
        cancel_scopes[task] = scope


async def check_cancelled():
    task = await curio.current_task()
    cancel_scope = get_cancel_scope(task)
    if cancel_scope is not None and cancel_scope._cancel_called:
        raise CancelledError


async def sleep(seconds: int):
    await check_cancelled()
    await curio.sleep(seconds)


@asynccontextmanager
@async_generator
async def open_cancel_scope():
    await check_cancelled()
    task = await curio.current_task()
    scope = CurioCancelScope()
    scope.add_task(task)
    parent_scope = get_cancel_scope(task)
    if parent_scope is not None:
        parent_scope.children.add(scope)

    set_cancel_scope(task, scope)
    try:
        await yield_(scope)
    finally:
        if parent_scope is not None:
            parent_scope.children.remove(scope)
            set_cancel_scope(task, scope)
        else:
            set_cancel_scope(task, None)


@asynccontextmanager
@async_generator
async def fail_after(delay: float):
    async with open_cancel_scope() as cancel_scope:
        async with curio.ignore_after(delay) as s:
            await yield_()

        if s.expired:
            await cancel_scope.cancel()
            raise TimeoutError


@asynccontextmanager
@async_generator
async def move_on_after(delay: float):
    async with curio.ignore_after(delay):
        await yield_()


#
# Task groups
#

class CurioTaskGroup:
    __slots__ = 'cancel_scope', '_active', '_tasks', '_host_task', '_exceptions'

    def __init__(self, cancel_scope: 'CurioCancelScope', host_task: curio.Task) -> None:
        self.cancel_scope = cancel_scope
        self._host_task = host_task
        self._active = True
        self._exceptions = []  # type: List[BaseException]
        self._tasks = set()  # type: Set[curio.Task]

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        task = await curio.spawn(func, *args, report_crash=False)
        task._taskgroup = self
        self._tasks.add(task)
        if name is not None:
            task.name = name

        # Make the spawned task inherit the current cancel scope
        current_task = await curio.current_task()
        cancel_scope = get_cancel_scope(current_task)
        cancel_scope.add_task(task)
        set_cancel_scope(task, cancel_scope)

    async def _task_done(self, task: curio.Task) -> None:
        self._tasks.remove(task)

    def _task_discard(self, task: curio.Task) -> None:
        # Remove the task from its cancel scope
        cancel_scope = get_cancel_scope(task)  # type: CurioCancelScope
        if cancel_scope is not None:
            cancel_scope.remove_task(task)

        self._tasks.discard(task)
        if task.terminated and task.exception is not None:
            if not isinstance(task.exception, (CancelledError, curio.TaskCancelled,
                                               curio.CancelledError)):
                self._exceptions.append(task.exception)


@asynccontextmanager
@async_generator
async def create_task_group():
    async with open_cancel_scope() as cancel_scope:
        current_task = await curio.current_task()
        group = CurioTaskGroup(cancel_scope, current_task)
        try:
            with translate_exceptions():
                await yield_(group)
        except CancelledError:
            await cancel_scope.cancel()
        except BaseException as exc:
            group._exceptions.append(exc)
            await cancel_scope.cancel()

        while group._tasks:
            for task in set(group._tasks):
                await task.wait()

        group._active = False
        if len(group._exceptions) > 1:
            raise ExceptionGroup(group._exceptions)
        elif group._exceptions:
            raise group._exceptions[0]


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    def wrapper():
        asynclib = sys.modules[__name__]
        with claim_current_thread(asynclib):
            return func(*args)

    await check_cancelled()
    thread = await curio.spawn_thread(wrapper)
    return await thread.join()


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    return curio.AWAIT(func(*args))


#
# Async file I/O
#

async def aopen(*args, **kwargs):
    fp = await run_in_thread(partial(open, *args, **kwargs))
    return curio.file.AsyncFile(fp)


#
# Networking
#

class CurioSocket(BaseSocket):
    def _wait_readable(self) -> None:
        return wait_socket_readable(self._raw_socket)

    def _wait_writable(self) -> None:
        return wait_socket_writable(self._raw_socket)

    def _check_cancelled(self) -> Awaitable[None]:
        return check_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


class SocketStream(abc.SocketStream):
    __slots__ = '_socket', '_ssl_context', '_server_hostname'

    def __init__(self, sock: CurioSocket, ssl_context: Optional[SSLContext] = None,
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
        return await self._socket.sendall(data)

    async def start_tls(self, context: Optional[SSLContext] = None) -> None:
        ssl_context = context or self._ssl_context or ssl.create_default_context()
        await self._socket.start_tls(ssl_context, self._server_hostname)


class SocketStreamServer(abc.SocketStreamServer):
    __slots__ = '_socket', '_ssl_context'

    def __init__(self, sock: CurioSocket, ssl_context: Optional[SSLContext]) -> None:
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

    def __init__(self, sock: CurioSocket) -> None:
        self._socket = sock

    def close(self):
        self._socket.close()

    @property
    def address(self) -> Union[Tuple[str, int], str]:
        return self._socket.getsockname()

    async def receive(self, max_bytes: int) -> Tuple[bytes, str]:
        return await self._socket.recvfrom(max_bytes)

    async def send(self, data: bytes, address: Optional[IPAddressType] = None,
                   port: Optional[int] = None) -> None:
        if address is not None and port is not None:
            await self._socket.sendto(data, (str(address), port))
        else:
            await self._socket.send(data)


def create_socket(family: int = socket.AF_INET, type: int = socket.SOCK_STREAM, proto: int = 0,
                  fileno=None):
    raw_socket = socket.socket(family, type, proto, fileno)
    return CurioSocket(raw_socket)


def wait_socket_readable(sock):
    return curio.traps._read_wait(sock)


def wait_socket_writable(sock):
    return curio.traps._write_wait(sock)


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
        if bind_host is not None or bind_port is not None:
            await sock.bind((bind_host or '', bind_port or 0))

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
    async with curio.SignalQueue(*signals) as queue:
        await yield_(queue)


#
# Synchronization
#

class Lock(curio.Lock):
    async def __aenter__(self):
        await check_cancelled()
        return await super().__aenter__()


class Condition(curio.Condition):
    async def __aenter__(self):
        await check_cancelled()
        return await super().__aenter__()

    async def wait(self):
        await check_cancelled()
        return await super().wait()


class Event(curio.Event):
    async def wait(self):
        await check_cancelled()
        return await super().wait()


class Semaphore(curio.Semaphore):
    async def __aenter__(self):
        await check_cancelled()
        return await super().__aenter__()


class Queue(curio.Queue):
    async def get(self):
        await check_cancelled()
        return await super().get()

    async def put(self, item):
        await check_cancelled()
        return await super().put(item)


abc.TaskGroup.register(CurioTaskGroup)
abc.Socket.register(curio.socket.SocketType)
abc.Lock.register(Lock)
abc.Condition.register(Condition)
abc.Event.register(Event)
abc.Semaphore.register(Semaphore)
abc.Queue.register(Queue)
