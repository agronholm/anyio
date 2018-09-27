import asyncio
import inspect
import os
import socket
import ssl
import sys
from contextlib import suppress
from ssl import SSLContext
from threading import Thread
from typing import Callable, Set, Optional, List, Union, Dict, Tuple  # noqa: F401

from async_generator import async_generator, yield_, asynccontextmanager

from .base import BaseSocket
from .. import interfaces, claim_current_thread, _local, T_Retval, IPAddressType
from ..exceptions import ExceptionGroup, CancelledError, DelimiterNotFound
from ..interfaces import BufferType

try:
    from asyncio import run as native_run, create_task, get_running_loop, current_task
except ImportError:
    # Snatched from the standard library
    def native_run(main, *, debug=False):
        """Run a coroutine.

        This function runs the passed coroutine, taking care of
        managing the asyncio event loop and finalizing asynchronous
        generators.

        This function cannot be called when another asyncio event loop is
        running in the same thread.

        If debug is True, the event loop will be run in debug mode.

        This function always creates a new event loop and closes it at the end.
        It should be used as a main entry point for asyncio programs, and should
        ideally only be called once.

        Example:

            async def main():
                await asyncio.sleep(1)
                print('hello')

            asyncio.run(main())
        """
        from asyncio import events, coroutines

        if events._get_running_loop() is not None:
            raise RuntimeError(
                "asyncio.run() cannot be called from a running event loop")

        if not coroutines.iscoroutine(main):
            raise ValueError("a coroutine was expected, got {!r}".format(main))

        loop = events.new_event_loop()
        try:
            events.set_event_loop(loop)
            loop.set_debug(debug)
            return loop.run_until_complete(main)
        finally:
            try:
                _cancel_all_tasks(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
            finally:
                events.set_event_loop(None)
                loop.close()

    def _cancel_all_tasks(loop):
        from asyncio import Task, gather

        to_cancel = Task.all_tasks(loop)
        if not to_cancel:
            return

        for task in to_cancel:
            task.cancel()

        loop.run_until_complete(
            gather(*to_cancel, loop=loop, return_exceptions=True))

        for task in to_cancel:
            if task.cancelled():
                continue
            if task.exception() is not None:
                loop.call_exception_handler({
                    'message': 'unhandled exception during asyncio.run() shutdown',
                    'exception': task.exception(),
                    'task': task,
                })

    def create_task(coro) -> asyncio.Task:
        return get_running_loop().create_task(coro)

    get_running_loop = asyncio._get_running_loop
    current_task = asyncio.Task.current_task

_create_task_supports_name = 'name' in inspect.signature(create_task).parameters


def run(func: Callable[..., T_Retval], *args,
        policy: Optional[asyncio.AbstractEventLoopPolicy] = None) -> T_Retval:
    if policy is not None:
        asyncio.set_event_loop_policy(policy)

    _local.cancel_scopes_by_task = {}  # type: Dict[asyncio.Task, AsyncIOCancelScope]
    return native_run(func(*args))


#
# Timeouts and cancellation
#


def _check_cancelled():
    cancel_scope = _local.cancel_scopes_by_task.get(current_task())
    if cancel_scope is not None and cancel_scope._cancel_called:
        raise CancelledError


async def sleep(delay: float) -> None:
    _check_cancelled()
    await asyncio.sleep(delay)


class AsyncIOCancelScope(interfaces.CancelScope):
    __slots__ = 'children', '_tasks', '_cancel_called'

    def __init__(self) -> None:
        self.children = set()  # type: Set[AsyncIOCancelScope]
        self._tasks = set()  # type: Set[asyncio.Task]
        self._cancel_called = False

    def add_task(self, task: asyncio.Task) -> None:
        self._tasks.add(task)
        _local.cancel_scopes_by_task[task] = self
        task.add_done_callback(self._task_done)

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.remove(task)
        del _local.cancel_scopes_by_task[task]

    async def cancel(self):
        if not self._cancel_called:
            self._cancel_called = True

            # Cancel all tasks that have started (i.e. they're awaiting on something)
            for task in self._tasks:
                coro = task._coro  # dirty, but works with both the stdlib event loop and uvloop
                if coro.cr_await is not None:
                    task.cancel()

            for child in self.children:
                await child.cancel()


@asynccontextmanager
@async_generator
async def open_cancel_scope():
    task = current_task()
    scope = AsyncIOCancelScope()
    scope.add_task(task)
    parent_scope = _local.cancel_scopes_by_task.get(task)
    if parent_scope is not None:
        parent_scope.children.add(scope)

    try:
        await yield_(scope)
    finally:
        if parent_scope is not None:
            parent_scope.children.remove(scope)
            _local.cancel_scopes_by_task[task] = parent_scope
        else:
            del _local.cancel_scopes_by_task[task]


@asynccontextmanager
@async_generator
async def fail_after(delay: float):
    async def timeout():
        nonlocal timeout_expired
        await sleep(delay)
        timeout_expired = True
        await scope.cancel()

    timeout_expired = False
    async with open_cancel_scope() as scope:
        timeout_task = get_running_loop().create_task(timeout())
        try:
            await yield_(scope)
        except asyncio.CancelledError as exc:
            if timeout_expired:
                await scope.cancel()
                raise TimeoutError().with_traceback(exc.__traceback__) from None
            else:
                raise
        finally:
            timeout_task.cancel()
            await asyncio.gather(timeout_task, return_exceptions=True)


@asynccontextmanager
@async_generator
async def move_on_after(delay: float):
    async def timeout():
        nonlocal timeout_expired
        await sleep(delay)
        timeout_expired = True
        await scope.cancel()

    timeout_expired = False
    async with open_cancel_scope() as scope:
        timeout_task = get_running_loop().create_task(timeout())
        try:
            await yield_(scope)
        except asyncio.CancelledError:
            if timeout_expired:
                await scope.cancel()
            else:
                raise
        finally:
            timeout_task.cancel()
            await asyncio.gather(timeout_task, return_exceptions=True)


#
# Task groups
#

class AsyncIOTaskGroup:
    __slots__ = 'cancel_scope', '_active', '_tasks', '_host_task', '_exceptions'

    def __init__(self, cancel_scope: 'AsyncIOCancelScope', host_task: asyncio.Task) -> None:
        self.cancel_scope = cancel_scope
        self._host_task = host_task
        self._active = True
        self._exceptions = []  # type: List[BaseException]
        self._tasks = set()  # type: Set[asyncio.Task]

    def _task_done(self, task: asyncio.Task) -> None:
        self._tasks.remove(task)
        if not task.cancelled():
            exc = task.exception()
            if exc is not None and not isinstance(exc, CancelledError):
                self._exceptions.append(exc)
                self._host_task.cancel()

    async def spawn(self, func: Callable, *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        if _create_task_supports_name:
            task = create_task(func(*args), name=name)
        else:
            task = create_task(func(*args))

        self._tasks.add(task)
        task.add_done_callback(self._task_done)

        # Make the spawned task inherit the task group's cancel scope
        _local.cancel_scopes_by_task[task] = self.cancel_scope
        self.cancel_scope.add_task(task)


@asynccontextmanager
@async_generator
async def open_task_group():
    async with open_cancel_scope() as cancel_scope:
        group = AsyncIOTaskGroup(cancel_scope, current_task())
        try:
            await yield_(group)
        except CancelledError:
            await cancel_scope.cancel()
        except BaseException as exc:
            group._exceptions.append(exc)
            await cancel_scope.cancel()

        while group._tasks:
            with suppress(asyncio.CancelledError):
                await asyncio.wait(group._tasks)

        group._active = False
        if len(group._exceptions) > 1:
            raise ExceptionGroup(group._exceptions)
        elif group._exceptions:
            raise group._exceptions[0]


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    def thread_worker():
        try:
            with claim_current_thread(asynclib):
                _local.loop = loop
                result = func(*args)
        except BaseException as exc:
            loop.call_soon_threadsafe(queue.put_nowait, (None, exc))
        else:
            loop.call_soon_threadsafe(queue.put_nowait, (result, None))

    asynclib = sys.modules[__name__]
    loop = get_running_loop()
    queue = asyncio.Queue(1)
    thread = Thread(target=thread_worker)
    thread.start()
    retval, exception = await queue.get()
    if exception is not None:
        raise exception
    else:
        return retval


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    f = asyncio.run_coroutine_threadsafe(func(*args), _local.loop)
    return f.result()


#
# Networking
#

class AsyncIOSocket(BaseSocket):
    __slots__ = '_loop', '_fileno'

    def __init__(self, raw_socket: socket.SocketType) -> None:
        self._loop = get_running_loop()
        self._fileno = raw_socket.fileno()
        super().__init__(raw_socket)

    async def _wait_readable(self) -> None:
        _check_cancelled()
        event = asyncio.Event()
        self._loop.add_reader(self._fileno, event.set)
        await event.wait()

    async def _wait_writable(self) -> None:
        _check_cancelled()
        event = asyncio.Event()
        self._loop.add_writer(self._fileno, event.set)
        await event.wait()

    async def _check_cancelled(self) -> None:
        _check_cancelled()

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


class SocketStream(interfaces.SocketStream):
    __slots__ = '_socket', '_ssl_context', '_server_hostname'

    def __init__(self, sock: AsyncIOSocket, ssl_context: Optional[SSLContext] = None,
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
        return await self._socket.sendall(data)

    async def start_tls(self, context: Optional[SSLContext] = None) -> None:
        ssl_context = context or self._ssl_context or ssl.create_default_context()
        await self._socket.start_tls(ssl_context, self._server_hostname)


class SocketStreamServer(interfaces.SocketStreamServer):
    __slots__ = '_socket', '_ssl_context'

    def __init__(self, sock: AsyncIOSocket, ssl_context: Optional[SSLContext]) -> None:
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


class AsyncIODatagramSocket(interfaces.DatagramSocket):
    __slots__ = '_socket'

    def __init__(self, sock: AsyncIOSocket) -> None:
        self._socket = sock

    async def receive(self, max_bytes: int) -> Tuple[bytes, str]:
        return await self._socket.recvfrom(max_bytes)

    async def send(self, data: bytes, address: Optional[IPAddressType] = None,
                   port: Optional[int] = None) -> None:
        if address is not None and port is not None:
            await self._socket.sendto(data, str(address))
        else:
            await self._socket.send(data)


def create_socket(family: int = socket.AF_INET, type: int = socket.SOCK_STREAM, proto: int = 0,
                  fileno=None) -> AsyncIOSocket:
    _check_cancelled()
    raw_socket = socket.socket(family, type, proto, fileno)
    return AsyncIOSocket(raw_socket)


async def wait_socket_readable(sock: socket.SocketType) -> None:
    _check_cancelled()
    event = asyncio.Event()
    get_running_loop().add_reader(sock.fileno(), event.set)
    await event.wait()


async def wait_socket_writable(sock: socket.SocketType) -> None:
    _check_cancelled()
    event = asyncio.Event()
    get_running_loop().add_writer(sock.fileno(), event.set)
    await event.wait()


@asynccontextmanager
@async_generator
async def connect_tcp(
        address: str, port: int, *, tls: Union[bool, SSLContext] = False,
        bind_host: Optional[str] = None, bind_port: Optional[int] = None):
    sock = create_socket()

    if bind_host is not None and bind_port is not None:
        await sock.bind((bind_host, bind_port))

    await sock.connect((address, port))
    stream = SocketStream(sock, server_hostname=address)

    if isinstance(tls, SSLContext):
        await stream.start_tls(tls)
    elif tls:
        await stream.start_tls()

    await yield_(stream)
    sock.close()


@asynccontextmanager
@async_generator
async def connect_unix(path: str):
    sock = create_socket(socket.AF_UNIX)
    await sock.connect(path)
    await yield_(SocketStream(sock))
    sock.close()


@asynccontextmanager
@async_generator
async def create_tcp_server(port: int, interface: Optional[str], *,
                            ssl_context: Optional[SSLContext] = None):
    sock = create_socket()
    await sock.bind((interface, port))
    sock.listen()
    await yield_(SocketStreamServer(sock, ssl_context))
    sock.close()


@asynccontextmanager
@async_generator
async def create_unix_server(path: str, *, mode: Optional[int] = None):
    sock = create_socket(socket.AF_UNIX)
    await sock.bind(path)

    if mode is not None:
        os.chmod(path, mode)

    sock.listen()
    await yield_(SocketStreamServer(sock, None))
    sock.close()


@asynccontextmanager
@async_generator
async def create_udp_socket(
        *, bind_host: Optional[str] = None, bind_port: Optional[int] = None,
        target_host: Optional[str] = None, target_port: Optional[int] = None):
    sock = create_socket(type=socket.SOCK_DGRAM)

    if bind_port is not None:
        await sock.bind((bind_host, bind_port))

    if target_host is not None and target_port is not None:
        await sock.connect((target_host, target_port))

    await yield_(AsyncIODatagramSocket(sock))
    sock.close()


#
# Synchronization
#

class Lock(asyncio.Lock):
    async def __aenter__(self):
        _check_cancelled()
        await self.acquire()

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self.release()


class Condition(asyncio.Condition):
    async def __aenter__(self):
        _check_cancelled()
        return await super().__aenter__()

    async def notify(self, n=1):
        super().notify(n)

    async def notify_all(self):
        super().notify(len(self._waiters))

    async def wait(self):
        _check_cancelled()
        return super().wait()


class Event(asyncio.Event):
    async def set(self):
        super().set()

    def wait(self):
        _check_cancelled()
        return super().wait()


class Semaphore(asyncio.Semaphore):
    def __aenter__(self):
        _check_cancelled()
        return super().__aenter__()

    @property
    def value(self):
        return self._value


class Queue(asyncio.Queue):
    def get(self):
        _check_cancelled()
        return super().get()

    def put(self, item):
        _check_cancelled()
        return super().put(item)


interfaces.TaskGroup.register(AsyncIOTaskGroup)
interfaces.SocketStream.register(SocketStream)
interfaces.SocketStreamServer.register(SocketStreamServer)
interfaces.Lock.register(Lock)
interfaces.Condition.register(Condition)
interfaces.Event.register(Event)
interfaces.Semaphore.register(Semaphore)
interfaces.Queue.register(Queue)
