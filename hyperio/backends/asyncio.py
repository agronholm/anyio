import asyncio
import inspect
import socket
import ssl
import sys
from contextlib import closing, suppress
from pathlib import Path
from socket import SocketType
from ssl import SSLContext
from threading import Thread
from typing import Callable, Set, Optional, List, Union, Iterable, AsyncIterable, Dict  # noqa:F401

from async_generator import async_generator, yield_, asynccontextmanager

from .. import (
    interfaces, IPAddressType, StreamingSocket, DatagramSocket, claim_current_thread, _local,
    T_Retval)
from ..exceptions import MultiError, DelimiterNotFound, CancelledError

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
            raise MultiError(group._exceptions)
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

class AsyncIOSocket:
    __slots__ = '_loop', '_sock'

    def __init__(self, sock: SocketType) -> None:
        self._loop = get_running_loop()
        self._sock = sock

    async def __aenter__(self) -> 'AsyncIOSocket':
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        self._sock.close()

    async def read(self, size: Optional[int] = None) -> bytes:
        return await self._loop.sock_recv(self._sock, size)

    async def send(self, data: bytes) -> None:
        await self._loop.sock_sendall(self._sock, data)


class AsyncIOStreamingSocket(AsyncIOSocket, interfaces.StreamingSocket):
    __slots__ = ()

    async def read_exactly(self, nbytes: int) -> bytes:
        buf = b''
        while nbytes > 0:
            data = await self._loop.sock_recv(self._sock, nbytes)
            buf += data
            nbytes -= len(data)

        return buf

    async def read_until(self, delimiter: bytes, max_size: int) -> bytes:
        index = 0
        delimiter_size = len(delimiter)
        buf = b''
        while len(buf) < max_size:
            data = await self._loop.sock_recv(self._sock, max_size - len(buf))
            buf += data
            if buf.find(delimiter, index):
                return buf
            else:
                index += len(data) - delimiter_size + 1

        raise DelimiterNotFound(
            'Maximum number of bytes ({}) read while searching for delimiter ({})'.format(
                max_size, delimiter))

    async def start_tls(self, ssl_context: SSLContext) -> None:
        def ready_callback():
            try:
                sslsock.do_handshake()
            except ssl.SSLWantReadError:
                print('Want SSL read')
            except ssl.SSLWantWriteError:
                print('Want SSL write')
            except BaseException as exc:
                future.set_exception(exc)
            else:
                future.set_result(None)

        sslsock = ssl_context.wrap_socket(self._sock)
        future = self._loop.create_future()
        self._loop.add_reader(self._sock.fileno(), ready_callback)
        self._loop.add_writer(self._sock.fileno(), ready_callback)
        try:
            await future
        finally:
            self._loop.remove_reader(self._sock.fileno())
            self._loop.remove_writer(self._sock.fileno())

        self._sock = sslsock


class AsyncIODatagramSocket(AsyncIOSocket, interfaces.DatagramSocket):
    __slots__ = ()

    async def send(self, data: bytes, address: Optional[IPAddressType] = None) -> None:
        if address:
            self._sock.connect(str(address))

        await self._loop.sock_sendall(data)


async def connect_tcp(
        address: IPAddressType, port: int, *,
        bind: Union[IPAddressType, Iterable[IPAddressType], None] = None) -> StreamingSocket:
    _check_cancelled()
    sock = socket.socket()
    sock.setblocking(False)
    loop = get_running_loop()
    await loop.sock_connect(sock, (address, port))
    return AsyncIOStreamingSocket(sock)


async def connect_unix(path: Union[str, Path]) -> StreamingSocket:
    _check_cancelled()
    sock = socket.socket(socket.AF_UNIX)
    sock.setblocking(False)
    loop = get_running_loop()
    await loop.sock_connect(sock, str(path))
    return AsyncIOStreamingSocket(sock)


@async_generator
async def serve_tcp(
        port: int, *, bind: Union[IPAddressType, Iterable[IPAddressType]] = '*',
        ssl_context: Optional[SSLContext] = None) -> AsyncIterable[StreamingSocket]:
    _check_cancelled()
    with closing(socket.socket()) as server_sock:
        server_sock.setblocking(False)
        server_sock.bind((str(bind), port))
        server_sock.listen(5)
        while True:
            raw_sock, address = await _local.loop.sock_accept(server_sock)
            stream = AsyncIOStreamingSocket(raw_sock)
            del raw_sock, address
            await yield_(stream)


async def create_udp_socket(
        *, bind: Union[IPAddressType, Iterable[IPAddressType], None] = None,
        target: Optional[IPAddressType] = None) -> DatagramSocket:
    _check_cancelled()
    sock = socket.socket()
    sock.setblocking(False)
    if target is not None:
        sock.connect(target)

    return AsyncIODatagramSocket(sock)


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


interfaces.CancelScope.register(AsyncIOCancelScope)
interfaces.TaskGroup.register(AsyncIOTaskGroup)
interfaces.Lock.register(Lock)
interfaces.Condition.register(Condition)
interfaces.Event.register(Event)
interfaces.Semaphore.register(Semaphore)
interfaces.Queue.register(Queue)
