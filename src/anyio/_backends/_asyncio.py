import asyncio
import concurrent.futures
import math
import socket
import sys
from collections import OrderedDict, deque
from concurrent.futures import Future
from dataclasses import dataclass
from functools import wraps
from inspect import isgenerator
from socket import AddressFamily, SocketKind, SocketType
from threading import Thread
from types import TracebackType
from typing import (
    Any, Awaitable, Callable, Coroutine, Deque, Dict, Generator, List, Optional, Sequence, Set,
    Tuple, Type, TypeVar, Union, cast)
from weakref import WeakKeyDictionary

from .. import TaskInfo, abc
from .._core._eventloop import claim_worker_thread, threadlocals
from .._core._exceptions import (
    BrokenResourceError, BusyResourceError, ClosedResourceError, EndOfStream)
from .._core._exceptions import ExceptionGroup as BaseExceptionGroup
from .._core._exceptions import WouldBlock
from .._core._sockets import GetAddrInfoReturnType, convert_ipv6_sockaddr
from .._core._synchronization import ResourceGuard
from ..abc.sockets import IPSockAddrType, UDPPacketType

if sys.version_info >= (3, 7):
    from asyncio import all_tasks, create_task, current_task, get_running_loop
    from asyncio import run as native_run
    from contextlib import asynccontextmanager
else:
    from async_generator import asynccontextmanager

    _T = TypeVar('_T')

    def native_run(main, *, debug=False):
        # Snatched from Python 3.7
        from asyncio import coroutines, events, tasks

        def _cancel_all_tasks(loop):
            to_cancel = all_tasks(loop)
            if not to_cancel:
                return

            for task in to_cancel:
                task.cancel()

            loop.run_until_complete(
                tasks.gather(*to_cancel, loop=loop, return_exceptions=True))

            for task in to_cancel:
                if task.cancelled():
                    continue
                if task.exception() is not None:
                    loop.call_exception_handler({
                        'message': 'unhandled exception during asyncio.run() shutdown',
                        'exception': task.exception(),
                        'task': task,
                    })

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

    def create_task(coro: Union[Generator[Any, None, _T], Awaitable[_T]], *,  # type: ignore
                    name: Optional[str] = None) -> asyncio.Task:
        return get_running_loop().create_task(coro)

    def get_running_loop() -> asyncio.AbstractEventLoop:
        loop = asyncio._get_running_loop()
        if loop is not None:
            return loop
        else:
            raise RuntimeError('no running event loop')

    def all_tasks(loop: Optional[asyncio.AbstractEventLoop] = None) -> Set[asyncio.Task]:
        """Return a set of all tasks for the loop."""
        from asyncio import Task

        if loop is None:
            loop = get_running_loop()

        return {t for t in Task.all_tasks(loop) if not t.done()}

    def current_task(loop: Optional[asyncio.AbstractEventLoop] = None) -> Optional[asyncio.Task]:
        if loop is None:
            loop = get_running_loop()

        return asyncio.Task.current_task(loop)

T_Retval = TypeVar('T_Retval')

# Check whether there is native support for task names in asyncio (3.8+)
_native_task_names = hasattr(asyncio.Task, 'get_name')


def get_callable_name(func: Callable) -> str:
    module = getattr(func, '__module__', None)
    qualname = getattr(func, '__qualname__', None)
    return '.'.join([x for x in (module, qualname) if x])


#
# Event loop
#

def _maybe_set_event_loop_policy(policy: Optional[asyncio.AbstractEventLoopPolicy],
                                 use_uvloop: bool) -> None:
    # On CPython, use uvloop when possible if no other policy has been given and if not
    # explicitly disabled
    if policy is None and use_uvloop and sys.implementation.name == 'cpython':
        try:
            import uvloop
        except ImportError:
            pass
        else:
            # Test for missing shutdown_default_executor() (uvloop 0.14.0 and earlier)
            if (not hasattr(asyncio.AbstractEventLoop, 'shutdown_default_executor')
                    or hasattr(uvloop.loop.Loop, 'shutdown_default_executor')):
                policy = uvloop.EventLoopPolicy()

    if policy is not None:
        asyncio.set_event_loop_policy(policy)


def run(func: Callable[..., T_Retval], *args, debug: bool = False, use_uvloop: bool = True,
        policy: Optional[asyncio.AbstractEventLoopPolicy] = None) -> T_Retval:
    @wraps(func)
    async def wrapper():
        task = current_task()
        task_state = TaskState(None, get_callable_name(func), None)
        _task_states[task] = task_state
        if _native_task_names:
            task.set_name(task_state.name)

        try:
            return await func(*args)
        finally:
            del _task_states[task]

    _maybe_set_event_loop_policy(policy, use_uvloop)
    return native_run(wrapper(), debug=debug)


#
# Miscellaneous
#

async def sleep(delay: float) -> None:
    await checkpoint()
    await asyncio.sleep(delay)


#
# Timeouts and cancellation
#

CancelledError = asyncio.CancelledError


class CancelScope(abc.CancelScope):
    __slots__ = ('_deadline', '_shield', '_parent_scope', '_cancel_called', '_active',
                 '_timeout_task', '_tasks', '_host_task', '_timeout_expired')

    def __init__(self, deadline: float = math.inf, shield: bool = False):
        self._deadline = deadline
        self._shield = shield
        self._parent_scope: Optional[CancelScope] = None
        self._cancel_called = False
        self._active = False
        self._timeout_task: Optional[asyncio.Task] = None
        self._tasks: Set[asyncio.Task] = set()
        self._host_task: Optional[asyncio.Task] = None
        self._timeout_expired = False

    async def __aenter__(self):
        async def timeout():
            await asyncio.sleep(self._deadline - get_running_loop().time())
            self._timeout_expired = True
            await self.cancel()

        if self._active:
            raise RuntimeError(
                "Each CancelScope may only be used for a single 'async with' block"
            )

        self._host_task = current_task()
        self._tasks.add(self._host_task)
        try:
            task_state = _task_states[self._host_task]
        except KeyError:
            task_name = self._host_task.get_name() if _native_task_names else None
            task_state = TaskState(None, task_name, self)
            _task_states[self._host_task] = task_state
        else:
            self._parent_scope = task_state.cancel_scope
            task_state.cancel_scope = self

        if self._deadline != math.inf:
            if get_running_loop().time() >= self._deadline:
                self._cancel_called = True
                self._timeout_expired = True
            else:
                self._timeout_task = get_running_loop().create_task(timeout())

        self._active = True
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        self._active = False
        if self._timeout_task:
            self._timeout_task.cancel()

        assert self._host_task is not None
        self._tasks.remove(self._host_task)
        host_task_state = _task_states.get(self._host_task)
        if host_task_state is not None and host_task_state.cancel_scope is self:
            host_task_state.cancel_scope = self._parent_scope

        if exc_val is not None:
            exceptions = exc_val.exceptions if isinstance(exc_val, ExceptionGroup) else [exc_val]
            if all(isinstance(exc, CancelledError) for exc in exceptions):
                if self._timeout_expired:
                    return True
                elif not self._parent_cancelled():
                    # This scope was directly cancelled
                    return True

        return None

    async def _cancel(self):
        # Deliver cancellation to directly contained tasks and nested cancel scopes
        this_task = current_task()
        for task in self._tasks:
            # Cancel the task directly, but only if it's blocked and isn't within a shielded scope
            cancel_scope = _task_states[task].cancel_scope
            if cancel_scope is self:
                # Only deliver the cancellation if the task is already running (but not this task!)
                if task is this_task:
                    continue

                if isgenerator(task._coro):  # type: ignore
                    awaitable = task._coro.gi_yieldfrom
                elif asyncio.iscoroutine(task._coro) and hasattr(task._coro, 'cr_await'):
                    awaitable = task._coro.cr_await
                else:
                    awaitable = task._coro

                if awaitable is not None:
                    task.cancel()
            elif not cancel_scope._shielded_to(self):
                await cancel_scope._cancel()

    def _shielded_to(self, parent: Optional['CancelScope']) -> bool:
        # Check whether this task or any parent up to (but not including) the "parent" argument is
        # shielded
        cancel_scope: Optional[CancelScope] = self
        while cancel_scope is not None and cancel_scope is not parent:
            if cancel_scope._shield:
                return True
            else:
                cancel_scope = cancel_scope._parent_scope

        return False

    def _parent_cancelled(self) -> bool:
        # Check whether any parent has been cancelled
        cancel_scope = self._parent_scope
        while cancel_scope is not None and not cancel_scope._shield:
            if cancel_scope._cancel_called:
                return True
            else:
                cancel_scope = cancel_scope._parent_scope

        return False

    async def cancel(self) -> None:
        if self._cancel_called:
            return

        self._cancel_called = True
        await self._cancel()

    @property
    def deadline(self) -> float:
        return self._deadline

    @property
    def cancel_called(self) -> bool:
        return self._cancel_called

    @property
    def shield(self) -> bool:
        return self._shield


async def checkpoint():
    try:
        cancel_scope = _task_states[current_task()].cancel_scope
    except KeyError:
        cancel_scope = None

    while cancel_scope:
        if cancel_scope.cancel_called:
            raise CancelledError
        elif cancel_scope.shield:
            break
        else:
            cancel_scope = cancel_scope._parent_scope

    await asyncio.sleep(0)


@asynccontextmanager
async def fail_after(delay: float, shield: bool):
    deadline = get_running_loop().time() + delay
    async with CancelScope(deadline, shield) as scope:
        yield scope

    if scope._timeout_expired:
        raise TimeoutError


@asynccontextmanager
async def move_on_after(delay: float, shield: bool):
    deadline = get_running_loop().time() + delay
    async with CancelScope(deadline=deadline, shield=shield) as scope:
        yield scope


async def current_effective_deadline():
    deadline = math.inf
    cancel_scope = _task_states[current_task()].cancel_scope
    while cancel_scope:
        deadline = min(deadline, cancel_scope.deadline)
        if cancel_scope.shield:
            break
        else:
            cancel_scope = cancel_scope._parent_scope

    return deadline


async def current_time():
    return get_running_loop().time()


#
# Task states
#

class TaskState:
    """
    Encapsulates auxiliary task information that cannot be added to the Task instance itself
    because there are no guarantees about its implementation.
    """

    __slots__ = 'parent_id', 'name', 'cancel_scope'

    def __init__(self, parent_id: Optional[int], name: Optional[str],
                 cancel_scope: Optional[CancelScope]):
        self.parent_id = parent_id
        self.name = name
        self.cancel_scope = cancel_scope


_task_states = WeakKeyDictionary()  # type: WeakKeyDictionary[asyncio.Task, TaskState]


#
# Task groups
#

class ExceptionGroup(BaseExceptionGroup):
    def __init__(self, exceptions: Sequence[BaseException]):
        super().__init__()
        self.exceptions = exceptions


class TaskGroup(abc.TaskGroup):
    __slots__ = 'cancel_scope', '_active', '_exceptions'

    def __init__(self):
        self.cancel_scope: CancelScope = CancelScope()
        self._active = False
        self._exceptions: List[BaseException] = []

    async def __aenter__(self):
        await self.cancel_scope.__aenter__()
        self._active = True
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        ignore_exception = await self.cancel_scope.__aexit__(exc_type, exc_val, exc_tb)
        if exc_val is not None:
            await self.cancel_scope.cancel()
            if not ignore_exception:
                self._exceptions.append(exc_val)

        while self.cancel_scope._tasks:
            try:
                await asyncio.wait(self.cancel_scope._tasks)
            except asyncio.CancelledError:
                await self.cancel_scope.cancel()

        self._active = False
        if not self.cancel_scope._parent_cancelled():
            exceptions = self._filter_cancellation_errors(self._exceptions)
        else:
            exceptions = self._exceptions

        try:
            if len(exceptions) > 1:
                raise ExceptionGroup(exceptions)
            elif exceptions and exceptions[0] is not exc_val:
                raise exceptions[0]
        except BaseException as exc:
            # Clear the context here, as it can only be done in-flight.
            # If the context is not cleared, it can result in recursive tracebacks (see #145).
            exc.__context__ = None
            raise

        return ignore_exception

    @staticmethod
    def _filter_cancellation_errors(exceptions: Sequence[BaseException]) -> List[BaseException]:
        filtered_exceptions: List[BaseException] = []
        for exc in exceptions:
            if isinstance(exc, ExceptionGroup):
                exc.exceptions = TaskGroup._filter_cancellation_errors(exc.exceptions)
                if exc.exceptions:
                    if len(exc.exceptions) > 1:
                        filtered_exceptions.append(exc)
                    else:
                        filtered_exceptions.append(exc.exceptions[0])
            elif not isinstance(exc, CancelledError):
                filtered_exceptions.append(exc)

        return filtered_exceptions

    async def _run_wrapped_task(self, func: Callable[..., Coroutine], args: tuple) -> None:
        task = cast(asyncio.Task, current_task())
        try:
            await func(*args)
        except BaseException as exc:
            self._exceptions.append(exc)
            await self.cancel_scope.cancel()
        finally:
            self.cancel_scope._tasks.remove(task)
            del _task_states[task]  # type: ignore

    async def spawn(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        name = name or get_callable_name(func)
        if _native_task_names:
            task = create_task(self._run_wrapped_task(func, args), name=name)  # type: ignore
        else:
            task = create_task(self._run_wrapped_task(func, args))

        # Make the spawned task inherit the task group's cancel scope
        _task_states[task] = TaskState(parent_id=id(current_task()), name=name,
                                       cancel_scope=self.cancel_scope)
        self.cancel_scope._tasks.add(task)


#
# Threads
#

_Retval_Queue_Type = Tuple[Optional[T_Retval], Optional[BaseException]]


async def run_sync_in_worker_thread(
        func: Callable[..., T_Retval], *args, cancellable: bool = False,
        limiter: Optional['CapacityLimiter'] = None) -> T_Retval:
    def thread_worker():
        try:
            with claim_worker_thread('asyncio'):
                threadlocals.loop = loop
                result = func(*args)
        except BaseException as exc:
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(limiter.release_on_behalf_of(task), loop)
                if not cancelled:
                    loop.call_soon_threadsafe(queue.put_nowait, (None, exc))
        else:
            if not loop.is_closed():
                asyncio.run_coroutine_threadsafe(limiter.release_on_behalf_of(task), loop)
                if not cancelled:
                    loop.call_soon_threadsafe(queue.put_nowait, (result, None))

    await checkpoint()
    loop = get_running_loop()
    task = current_task()
    queue: asyncio.Queue[_Retval_Queue_Type] = asyncio.Queue(1)
    cancelled = False
    limiter = limiter or _default_thread_limiter
    await limiter.acquire_on_behalf_of(task)
    thread = Thread(target=thread_worker, daemon=True)
    thread.start()
    exception: Optional[BaseException] = None
    async with CancelScope(shield=not cancellable):
        try:
            retval, exception = await queue.get()
        except BaseException as exc:
            exception = exc
        finally:
            cancelled = True

    if exception is not None:
        raise exception
    else:
        return cast(T_Retval, retval)


def run_async_from_thread(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args) -> T_Retval:
    f: concurrent.futures.Future[T_Retval] = asyncio.run_coroutine_threadsafe(
        func(*args), threadlocals.loop)
    return f.result()


class BlockingPortal(abc.BlockingPortal):
    __slots__ = '_loop'

    def __init__(self):
        super().__init__()
        self._loop = get_running_loop()

    def _spawn_task_from_thread(self, func: Callable, args: tuple, future: Future) -> None:
        asyncio.run_coroutine_threadsafe(
            self._task_group.spawn(self._call_func, func, args, future), self._loop)


#
# Subprocesses
#

@dataclass
class StreamReaderWrapper(abc.ByteReceiveStream):
    _stream: asyncio.StreamReader

    async def receive(self, max_bytes: int = 65536) -> bytes:
        data = await self._stream.read(max_bytes)
        if data:
            return data
        else:
            raise EndOfStream

    async def aclose(self) -> None:
        self._stream.feed_eof()


@dataclass
class StreamWriterWrapper(abc.ByteSendStream):
    _stream: asyncio.StreamWriter

    async def send(self, item: bytes) -> None:
        self._stream.write(item)
        await self._stream.drain()

    async def aclose(self) -> None:
        self._stream.close()


@dataclass
class Process(abc.Process):
    _process: asyncio.subprocess.Process
    _stdin: Optional[abc.ByteSendStream]
    _stdout: Optional[abc.ByteReceiveStream]
    _stderr: Optional[abc.ByteReceiveStream]

    async def aclose(self) -> None:
        if self._stdin:
            await self._stdin.aclose()
        if self._stdout:
            await self._stdout.aclose()
        if self._stderr:
            await self._stderr.aclose()

        await self.wait()

    async def wait(self) -> int:
        return await self._process.wait()

    def terminate(self) -> None:
        self._process.terminate()

    def kill(self) -> None:
        self._process.kill()

    def send_signal(self, signal: int) -> None:
        self._process.send_signal(signal)

    @property
    def pid(self) -> int:
        return self._process.pid

    @property
    def returncode(self) -> Optional[int]:
        return self._process.returncode

    @property
    def stdin(self) -> Optional[abc.ByteSendStream]:
        return self._stdin

    @property
    def stdout(self) -> Optional[abc.ByteReceiveStream]:
        return self._stdout

    @property
    def stderr(self) -> Optional[abc.ByteReceiveStream]:
        return self._stderr


async def open_process(command, *, shell: bool, stdin: int, stdout: int, stderr: int):
    await checkpoint()
    if shell:
        process = await asyncio.create_subprocess_shell(command, stdin=stdin, stdout=stdout,
                                                        stderr=stderr)
    else:
        process = await asyncio.create_subprocess_exec(*command, stdin=stdin, stdout=stdout,
                                                       stderr=stderr)

    stdin_stream = StreamWriterWrapper(process.stdin) if process.stdin else None
    stdout_stream = StreamReaderWrapper(process.stdout) if process.stdout else None
    stderr_stream = StreamReaderWrapper(process.stderr) if process.stderr else None
    return Process(process, stdin_stream, stdout_stream, stderr_stream)


#
# Sockets and networking
#

_read_events: Dict[socket.SocketType, asyncio.Event] = {}
_write_events: Dict[socket.SocketType, asyncio.Event] = {}


class StreamProtocol(asyncio.Protocol):
    read_queue: Deque[bytes]
    read_event: asyncio.Event
    write_future: asyncio.Future
    exception: Optional[Exception] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.read_queue = deque()
        self.read_event = asyncio.Event()
        self.write_future = asyncio.Future()
        self.write_future.set_result(None)
        cast(asyncio.Transport, transport).set_write_buffer_limits(0)

    def connection_lost(self, exc: Optional[Exception]) -> None:
        if exc:
            self.exception = BrokenResourceError()
            self.exception.__cause__ = exc

        self.read_event.set()
        self.write_future = asyncio.Future()
        if self.exception:
            self.write_future.set_exception(self.exception)
        else:
            self.write_future.set_result(None)

    def data_received(self, data: bytes) -> None:
        self.read_queue.append(data)
        self.read_event.set()

    def eof_received(self) -> Optional[bool]:
        self.read_event.set()
        return True

    def pause_writing(self) -> None:
        self.write_future = asyncio.Future()

    def resume_writing(self) -> None:
        self.write_future.set_result(None)


class DatagramProtocol(asyncio.DatagramProtocol):
    read_queue: Deque[Tuple[bytes, IPSockAddrType]]
    read_event: asyncio.Event
    write_event: asyncio.Event
    exception: Optional[Exception] = None

    def connection_made(self, transport: asyncio.BaseTransport) -> None:
        self.read_queue = deque(maxlen=100)  # arbitrary value
        self.read_event = asyncio.Event()
        self.write_event = asyncio.Event()
        self.write_event.set()

    def connection_lost(self, exc: Optional[Exception]) -> None:
        self.read_event.set()
        self.write_event.set()

    def datagram_received(self, data: bytes, addr: IPSockAddrType) -> None:
        addr = convert_ipv6_sockaddr(addr)
        self.read_queue.append((data, addr))
        self.read_event.set()

    def error_received(self, exc: Exception) -> None:
        self.exception = exc

    def pause_writing(self) -> None:
        self.write_event.clear()

    def resume_writing(self) -> None:
        self.write_event.set()


class SocketStream(abc.SocketStream):
    def __init__(self, transport: asyncio.Transport, protocol: StreamProtocol):
        self._transport = transport
        self._protocol = protocol
        self._receive_guard = ResourceGuard('reading from')
        self._send_guard = ResourceGuard('writing to')
        self._closed = False

    @property
    def _raw_socket(self) -> socket.socket:
        return self._transport.get_extra_info('socket')

    async def receive(self, max_bytes: int = 65536) -> bytes:
        with self._receive_guard:
            await checkpoint()
            if not self._protocol.read_event.is_set() and not self._transport.is_closing():
                self._transport.resume_reading()
                await self._protocol.read_event.wait()
                self._transport.pause_reading()

            try:
                chunk = self._protocol.read_queue.popleft()
            except IndexError:
                if self._closed:
                    raise ClosedResourceError from None
                elif self._protocol.exception:
                    raise self._protocol.exception
                else:
                    raise EndOfStream

            if len(chunk) > max_bytes:
                # Split the oversized chunk
                chunk, leftover = chunk[:max_bytes], chunk[max_bytes:]
                self._protocol.read_queue.appendleft(leftover)

            # If the read queue is empty, clear the flag so that the next call will block until
            # data is available
            if not self._protocol.read_queue:
                self._protocol.read_event.clear()

        return chunk

    async def send(self, item: bytes) -> None:
        with self._send_guard:
            await checkpoint()
            try:
                self._transport.write(item)
            except RuntimeError as exc:
                if self._closed:
                    raise ClosedResourceError from None
                elif self._transport.is_closing():
                    raise BrokenResourceError from exc
                else:
                    raise

            await self._protocol.write_future

    async def send_eof(self) -> None:
        try:
            self._transport.write_eof()
        except OSError:
            pass

    async def aclose(self) -> None:
        if not self._transport.is_closing():
            self._closed = True
            try:
                self._transport.write_eof()
            except OSError:
                pass

            self._transport.close()
            await asyncio.sleep(0)
            self._transport.abort()


class SocketListener(abc.SocketListener):
    def __init__(self, raw_socket: socket.SocketType):
        self.__raw_socket = raw_socket
        self._loop = cast(asyncio.BaseEventLoop, get_running_loop())
        self._accept_guard = ResourceGuard('accepting connections from')

    @property
    def _raw_socket(self) -> socket.socket:
        return self.__raw_socket

    async def accept(self) -> abc.SocketStream:
        with self._accept_guard:
            await checkpoint()
            try:
                client_sock, _addr = await self._loop.sock_accept(self._raw_socket)
            except asyncio.CancelledError:
                # Workaround for https://bugs.python.org/issue41317
                try:
                    self._loop.remove_reader(self._raw_socket)
                except (ValueError, NotImplementedError):
                    if self._raw_socket.fileno() == -1:
                        raise ClosedResourceError from None

                raise

        if client_sock.family in (socket.AF_INET, socket.AF_INET6):
            client_sock.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        transport, protocol = await self._loop.connect_accepted_socket(StreamProtocol, client_sock)
        return SocketStream(cast(asyncio.Transport, transport), cast(StreamProtocol, protocol))

    async def aclose(self) -> None:
        # Needed on Windows + Python < 3.8
        try:
            self._loop.remove_reader(self._raw_socket)
        except NotImplementedError:
            pass

        self._raw_socket.close()


class UDPSocket(abc.UDPSocket):
    def __init__(self, transport: asyncio.DatagramTransport, protocol: DatagramProtocol):
        self._transport = transport
        self._protocol = protocol
        self._receive_guard = ResourceGuard('reading from')
        self._send_guard = ResourceGuard('writing to')
        self._closed = False

    @property
    def _raw_socket(self) -> SocketType:
        return self._transport.get_extra_info('socket')

    async def aclose(self) -> None:
        if not self._transport.is_closing():
            self._closed = True
            self._transport.close()

    async def receive(self) -> Tuple[bytes, IPSockAddrType]:
        with self._receive_guard:
            await checkpoint()

            # If the buffer is empty, ask for more data
            if not self._protocol.read_queue and not self._transport.is_closing():
                self._protocol.read_event.clear()
                await self._protocol.read_event.wait()

            try:
                return self._protocol.read_queue.popleft()
            except IndexError:
                if self._closed:
                    raise ClosedResourceError from None
                else:
                    raise BrokenResourceError from None

    async def send(self, item: UDPPacketType) -> None:
        with self._send_guard:
            await checkpoint()
            await self._protocol.write_event.wait()
            if self._closed:
                raise ClosedResourceError
            elif self._transport.is_closing():
                raise BrokenResourceError
            else:
                self._transport.sendto(*item)


class ConnectedUDPSocket(abc.ConnectedUDPSocket):
    def __init__(self, transport: asyncio.DatagramTransport, protocol: DatagramProtocol):
        self._transport = transport
        self._protocol = protocol
        self._receive_guard = ResourceGuard('reading from')
        self._send_guard = ResourceGuard('writing to')
        self._closed = False

    @property
    def _raw_socket(self) -> SocketType:
        return self._transport.get_extra_info('socket')

    async def aclose(self) -> None:
        if not self._transport.is_closing():
            self._closed = True
            self._transport.close()

    async def receive(self) -> bytes:
        with self._receive_guard:
            await checkpoint()

            # If the buffer is empty, ask for more data
            if not self._protocol.read_queue and not self._transport.is_closing():
                self._protocol.read_event.clear()
                await self._protocol.read_event.wait()

            try:
                packet = self._protocol.read_queue.popleft()
            except IndexError:
                if self._closed:
                    raise ClosedResourceError from None
                else:
                    raise BrokenResourceError from None

            return packet[0]

    async def send(self, item: bytes) -> None:
        with self._send_guard:
            await checkpoint()
            await self._protocol.write_event.wait()
            if self._closed:
                raise ClosedResourceError
            elif self._transport.is_closing():
                raise BrokenResourceError
            else:
                self._transport.sendto(item)


async def connect_tcp(host: str, port: int,
                      local_addr: Optional[Tuple[str, int]] = None) -> SocketStream:
    transport, protocol = cast(
        Tuple[asyncio.Transport, StreamProtocol],
        await get_running_loop().create_connection(StreamProtocol, host, port,
                                                   local_addr=local_addr)
    )
    transport.pause_reading()
    return SocketStream(transport, protocol)


async def connect_unix(path: str) -> SocketStream:
    transport, protocol = cast(
        Tuple[asyncio.Transport, StreamProtocol],
        await get_running_loop().create_unix_connection(StreamProtocol, path)
    )
    transport.pause_reading()
    return SocketStream(transport, protocol)


async def create_udp_socket(
    family: socket.AddressFamily,
    local_address: Optional[IPSockAddrType],
    remote_address: Optional[IPSockAddrType],
    reuse_port: bool
) -> Union[UDPSocket, ConnectedUDPSocket]:
    result = await get_running_loop().create_datagram_endpoint(
        DatagramProtocol, local_addr=local_address, remote_addr=remote_address, family=family,
        reuse_port=reuse_port)
    transport = cast(asyncio.DatagramTransport, result[0])
    protocol = cast(DatagramProtocol, result[1])
    if protocol.exception:
        transport.close()
        raise protocol.exception

    if not remote_address:
        return UDPSocket(transport, protocol)
    else:
        return ConnectedUDPSocket(transport, protocol)


async def getaddrinfo(host: Union[bytearray, bytes, str], port: Union[str, int, None], *,
                      family: Union[int, AddressFamily] = 0, type: Union[int, SocketKind] = 0,
                      proto: int = 0, flags: int = 0) -> GetAddrInfoReturnType:
    # https://github.com/python/typeshed/pull/4304
    result = await get_running_loop().getaddrinfo(
        host, port, family=family, type=type, proto=proto, flags=flags)  # type: ignore[arg-type]
    return cast(GetAddrInfoReturnType, result)


async def getnameinfo(sockaddr: IPSockAddrType, flags: int = 0) -> Tuple[str, str]:
    # https://github.com/python/typeshed/pull/4305
    result = await get_running_loop().getnameinfo(sockaddr, flags)
    return cast(Tuple[str, str], result)


async def wait_socket_readable(sock: socket.SocketType) -> None:
    await checkpoint()
    if _read_events.get(sock):
        raise BusyResourceError('reading from') from None

    loop = get_running_loop()
    event = _read_events[sock] = asyncio.Event()
    get_running_loop().add_reader(sock, event.set)
    try:
        await event.wait()
    finally:
        if _read_events.pop(sock, None) is not None:
            loop.remove_reader(sock)
            readable = True
        else:
            readable = False

    if not readable:
        raise ClosedResourceError


async def wait_socket_writable(sock: socket.SocketType) -> None:
    await checkpoint()
    if _write_events.get(sock):
        raise BusyResourceError('writing to') from None

    loop = get_running_loop()
    event = _write_events[sock] = asyncio.Event()
    loop.add_writer(sock.fileno(), event.set)
    try:
        await event.wait()
    finally:
        if _write_events.pop(sock, None) is not None:
            loop.remove_writer(sock)
            writable = True
        else:
            writable = False

    if not writable:
        raise ClosedResourceError


#
# Synchronization
#

class Lock(abc.Lock):
    def __init__(self):
        self._lock = asyncio.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self) -> None:
        await checkpoint()
        await self._lock.acquire()

    async def release(self) -> None:
        self._lock.release()


class Condition(abc.Condition):
    def __init__(self, lock: Optional[Lock]):
        asyncio_lock = lock._lock if lock else None
        self._condition = asyncio.Condition(asyncio_lock)

    async def acquire(self) -> None:
        await checkpoint()
        await self._condition.acquire()

    async def release(self) -> None:
        self._condition.release()

    def locked(self) -> bool:
        return self._condition.locked()

    async def notify(self, n=1):
        self._condition.notify(n)

    async def notify_all(self):
        self._condition.notify_all()

    async def wait(self):
        await checkpoint()
        return await self._condition.wait()


class Event(abc.Event):
    def __init__(self):
        self._event = asyncio.Event()

    async def set(self):
        self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self):
        await checkpoint()
        await self._event.wait()


class Semaphore(abc.Semaphore):
    def __init__(self, value: int):
        self._semaphore = asyncio.Semaphore(value)

    async def acquire(self) -> None:
        await checkpoint()
        await self._semaphore.acquire()

    async def release(self) -> None:
        self._semaphore.release()

    @property
    def value(self):
        return self._semaphore._value


class CapacityLimiter(abc.CapacityLimiter):
    def __init__(self, total_tokens: float):
        self._set_total_tokens(total_tokens)
        self._borrowers: Set[Any] = set()
        self._wait_queue: Dict[Any, asyncio.Event] = OrderedDict()

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        await self.release()

    def _set_total_tokens(self, value: float) -> None:
        if not isinstance(value, int) and not math.isinf(value):
            raise TypeError('total_tokens must be an int or math.inf')
        if value < 1:
            raise ValueError('total_tokens must be >= 1')

        self._total_tokens = value

    @property
    def total_tokens(self) -> float:
        return self._total_tokens

    async def set_total_tokens(self, value: float) -> None:
        old_value = self._total_tokens
        self._set_total_tokens(value)
        events = []
        for event in self._wait_queue.values():
            if value <= old_value:
                break

            if not event.is_set():
                events.append(event)
                old_value += 1

        for event in events:
            event.set()

    @property
    def borrowed_tokens(self) -> int:
        return len(self._borrowers)

    @property
    def available_tokens(self) -> float:
        return self._total_tokens - len(self._borrowers)

    async def acquire_nowait(self) -> None:
        await self.acquire_on_behalf_of_nowait(current_task())

    async def acquire_on_behalf_of_nowait(self, borrower) -> None:
        if borrower in self._borrowers:
            raise RuntimeError("this borrower is already holding one of this CapacityLimiter's "
                               "tokens")

        if self._wait_queue or len(self._borrowers) >= self._total_tokens:
            raise WouldBlock

        self._borrowers.add(borrower)

    async def acquire(self) -> None:
        return await self.acquire_on_behalf_of(current_task())

    async def acquire_on_behalf_of(self, borrower) -> None:
        try:
            await self.acquire_on_behalf_of_nowait(borrower)
        except WouldBlock:
            event = asyncio.Event()
            self._wait_queue[borrower] = event
            try:
                await event.wait()
            except BaseException:
                self._wait_queue.pop(borrower, None)
                raise

            self._borrowers.add(borrower)

    async def release(self) -> None:
        await self.release_on_behalf_of(current_task())

    async def release_on_behalf_of(self, borrower) -> None:
        try:
            self._borrowers.remove(borrower)
        except KeyError:
            raise RuntimeError("this borrower isn't holding any of this CapacityLimiter's "
                               "tokens") from None

        # Notify the next task in line if this limiter has free capacity now
        if self._wait_queue and len(self._borrowers) < self._total_tokens:
            event = self._wait_queue.popitem()[1]
            event.set()


def current_default_thread_limiter():
    return _default_thread_limiter


_default_thread_limiter = CapacityLimiter(40)


#
# Operating system signals
#

@asynccontextmanager
async def open_signal_receiver(*signals: int):
    async def process_signal_queue():
        while True:
            signum = await queue.get()
            yield signum

    loop = get_running_loop()
    queue = asyncio.Queue()  # type: asyncio.Queue[int]
    handled_signals = set()
    agen = process_signal_queue()
    await checkpoint()
    try:
        for sig in set(signals):
            loop.add_signal_handler(sig, queue.put_nowait, sig)
            handled_signals.add(sig)

        yield agen
    finally:
        await agen.aclose()
        for sig in handled_signals:
            loop.remove_signal_handler(sig)


#
# Testing and debugging
#

def _create_task_info(task: asyncio.Task) -> TaskInfo:
    task_state = _task_states.get(task)
    if task_state is None:
        name = task.get_name() if _native_task_names else None  # type: ignore
        parent_id = None
    else:
        name = task_state.name
        parent_id = task_state.parent_id

    return TaskInfo(id(task), parent_id, name, task._coro)  # type: ignore


async def get_current_task() -> TaskInfo:
    return _create_task_info(current_task())  # type: ignore


async def get_running_tasks() -> List[TaskInfo]:
    return [_create_task_info(task) for task in all_tasks() if not task.done()]


async def wait_all_tasks_blocked() -> None:
    this_task = current_task()
    while True:
        for task in all_tasks():
            if task is this_task:
                continue

            if isgenerator(task._coro):  # type: ignore
                awaitable = task._coro.gi_yieldfrom  # type: ignore
            elif hasattr(task._coro, 'cr_code'):  # type: ignore
                awaitable = task._coro.cr_await  # type: ignore
            else:
                awaitable = task._coro  # type: ignore

            # If the first awaitable is None, the task has not started running yet
            task_running = bool(awaitable)

            # Consider any task doing sleep(0) as not being blocked
            while asyncio.iscoroutine(awaitable):
                if isgenerator(awaitable):
                    code = awaitable.gi_code
                    f_locals = awaitable.gi_frame.f_locals
                    awaitable = awaitable.gi_yieldfrom
                elif hasattr(awaitable, 'cr_code'):
                    code = awaitable.cr_code
                    f_locals = awaitable.cr_frame.f_locals
                    awaitable = awaitable.cr_await
                else:
                    break

                if code is asyncio.sleep.__code__ and f_locals['delay'] == 0:
                    task_running = False
                    break

            if not task_running:
                await sleep(0.1)
                break
        else:
            return


class TestRunner(abc.TestRunner):
    def __init__(self, debug: bool = False, use_uvloop: bool = True,
                 policy: Optional[asyncio.AbstractEventLoopPolicy] = None):
        _maybe_set_event_loop_policy(policy, use_uvloop)
        self._loop = asyncio.new_event_loop()
        self._loop.set_debug(debug)
        asyncio.set_event_loop(self._loop)

    def _cancel_all_tasks(self):
        to_cancel = all_tasks(self._loop)
        if not to_cancel:
            return

        for task in to_cancel:
            task.cancel()

        self._loop.run_until_complete(
            asyncio.gather(*to_cancel, loop=self._loop, return_exceptions=True))

        for task in to_cancel:
            if task.cancelled():
                continue
            if task.exception() is not None:
                raise task.exception()

    def close(self) -> None:
        try:
            self._cancel_all_tasks()
            self._loop.run_until_complete(self._loop.shutdown_asyncgens())
        finally:
            asyncio.set_event_loop(None)
            self._loop.close()

    def call(self, func: Callable[..., Awaitable], *args, **kwargs):
        return self._loop.run_until_complete(func(*args, **kwargs))
