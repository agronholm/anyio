import inspect
import math
import socket
import sys
from collections import OrderedDict, defaultdict
from concurrent.futures import Future
from dataclasses import dataclass
from signal import signal
from socket import AddressFamily, SocketKind
from threading import Thread
from types import TracebackType
from typing import (
    Any, Awaitable, Callable, Coroutine, DefaultDict, Dict, Generic, List, NoReturn, Optional,
    Sequence, Set, Tuple, Type, TypeVar, Union, cast)
from weakref import WeakKeyDictionary

import curio.io
import curio.meta
import curio.socket
import curio.ssl
import curio.subprocess
import curio.traps

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
    from contextlib import asynccontextmanager
else:
    from async_generator import asynccontextmanager

T_Retval = TypeVar('T_Retval')
T_SockAddr = TypeVar('T_SockAddr', str, IPSockAddrType)


def get_callable_name(func: Callable) -> str:
    module = getattr(func, '__module__', None)
    qualname = getattr(func, '__qualname__', None)
    return '.'.join([x for x in (module, qualname) if x])


#
# Event loop
#

def run(func: Callable[..., T_Retval], *args, **curio_options) -> T_Retval:
    async def wrapper():
        nonlocal exception, retval
        try:
            retval = await func(*args)
        except BaseException as exc:
            exception = exc

    exception = retval = None
    coro = wrapper()
    coro.__qualname__ = get_callable_name(func)
    curio.run(coro, **curio_options)
    if exception is not None:
        raise exception
    else:
        return cast(T_Retval, retval)


#
# Miscellaneous functions
#

async def sleep(delay: float):
    await checkpoint()
    await curio.sleep(delay)


#
# Timeouts and cancellation
#

CancelledError = curio.TaskCancelled


class CancelScope(abc.CancelScope):
    __slots__ = ('_deadline', '_shield', '_parent_scope', '_cancel_called', '_active',
                 '_timeout_task', '_tasks', '_host_task', '_timeout_expired')

    def __init__(self, deadline: float = math.inf, shield: bool = False):
        self._deadline = deadline
        self._shield = shield
        self._parent_scope: Optional[CancelScope] = None
        self._cancel_called = False
        self._active = False
        self._timeout_task: Optional[curio.Task] = None
        self._tasks: Set[curio.Task] = set()
        self._host_task: Optional[curio.Task] = None
        self._timeout_expired = False

    async def __aenter__(self):
        async def timeout():
            await curio.sleep(self._deadline - await curio.clock())
            self._timeout_expired = True
            await self.cancel()

        if self._active:
            raise RuntimeError(
                "Each CancelScope may only be used for a single 'async with' block"
            )

        self._host_task = await curio.current_task()
        self._tasks.add(self._host_task)
        try:
            task_state = _task_states[self._host_task]
        except KeyError:
            task_state = TaskState(self)
            _task_states[self._host_task] = task_state
        else:
            self._parent_scope = task_state.cancel_scope
            task_state.cancel_scope = self

        if self._deadline != math.inf:
            if await curio.clock() >= self._deadline:
                self._cancel_called = True
                self._timeout_expired = True
            else:
                self._timeout_task = await curio.spawn(timeout)

        self._active = True
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        self._active = False
        if self._timeout_task:
            await self._timeout_task.cancel(blocking=False)

        if exc_type is curio.errors.TaskTimeout:
            if self._deadline != math.inf and await curio.clock() >= self._deadline:
                self._timeout_expired = True

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
        for task in self._tasks:
            # Cancel the task directly, but only if it's blocked and isn't within a shielded scope
            cancel_scope = _task_states[task].cancel_scope
            if cancel_scope is self:
                # Only deliver the cancellation if the task is already running (but not this task!)
                if not task.coro.cr_running and task.coro.cr_await is not None:
                    await task.cancel(blocking=False)

                    # Enable the task to be cancelled again
                    task.cancelled = False
            elif not cancel_scope._shielded_to(self):
                await cancel_scope._cancel()

    def _shielded_to(self, parent: 'CancelScope') -> bool:
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
        cancel_scope = _task_states[await curio.current_task()].cancel_scope
    except KeyError:
        cancel_scope = None

    while cancel_scope:
        if cancel_scope.cancel_called:
            raise CancelledError
        elif cancel_scope.shield:
            break
        else:
            cancel_scope = cancel_scope._parent_scope

    await curio.sleep(0)


@asynccontextmanager
async def fail_after(delay: float, shield: bool):
    deadline = await curio.clock() + delay
    async with CancelScope(deadline, shield) as scope:
        yield scope

    if scope._timeout_expired:
        raise TimeoutError from None


@asynccontextmanager
async def move_on_after(delay: float, shield: bool):
    deadline = await curio.clock() + delay
    async with CancelScope(deadline=deadline, shield=shield) as scope:
        yield scope


async def current_effective_deadline():
    deadline = math.inf
    cancel_scope = _task_states[await curio.current_task()].cancel_scope
    while cancel_scope:
        deadline = min(deadline, cancel_scope.deadline)
        if cancel_scope.shield:
            break
        else:
            cancel_scope = cancel_scope._parent_scope

    return deadline


async def current_time():
    return await curio.clock()


#
# Task states
#

class TaskState:
    """
    Encapsulates auxiliary task information that cannot be added to the Task instance itself
    because there are no upstream guarantees that no attribute conflicts will occur.
    """

    __slots__ = 'cancel_scope'

    def __init__(self, cancel_scope: Optional[CancelScope]):
        self.cancel_scope = cancel_scope


_task_states = WeakKeyDictionary()  # type: WeakKeyDictionary[curio.Task, TaskState]


#
# Task groups
#

class ExceptionGroup(BaseExceptionGroup):
    def __init__(self, exceptions: Sequence[BaseException]):
        super().__init__()
        self.exceptions = exceptions


class TaskGroup(abc.TaskGroup):
    __slots__ = 'cancel_scope', '_active', '_exceptions'

    def __init__(self) -> None:
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
            for task in self.cancel_scope._tasks.copy():
                try:
                    await task.wait()
                except curio.TaskCancelled:
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
        task = await curio.current_task()
        try:
            await func(*args)
        except BaseException as exc:
            self._exceptions.append(exc)
            await self.cancel_scope.cancel()
        finally:
            self.cancel_scope._tasks.remove(task)
            del _task_states[task]

    async def spawn(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        if not self._active:
            raise RuntimeError('This task group is not active; no new tasks can be spawned.')

        task = await curio.spawn(self._run_wrapped_task, func, args, daemon=True)
        task.parentid = (await curio.current_task()).id
        task.name = name or get_callable_name(func)

        # Make the spawned task inherit the task group's cancel scope
        _task_states[task] = TaskState(cancel_scope=self.cancel_scope)
        self.cancel_scope._tasks.add(task)


#
# Threads
#

async def run_sync_in_worker_thread(
        func: Callable[..., T_Retval], *args, cancellable: bool = False,
        limiter: Optional['CapacityLimiter'] = None) -> T_Retval:
    async def async_call_helper():
        while True:
            item = await queue.get()
            if item is None:
                await limiter.release_on_behalf_of(task)
                await finish_event.set()
                return

            func_: Callable
            args_: tuple
            future: Future
            func_, args_, future = item
            try:
                retval_ = await func_(*args_)
            except BaseException as exc_:
                future.set_exception(exc_)
            else:
                future.set_result(retval_)

    def thread_worker():
        nonlocal retval, exception
        try:
            with claim_worker_thread('curio'):
                threadlocals.queue = queue
                retval = func(*args)
        except BaseException as exc:
            exception = exc
        finally:
            if not helper_task.cancelled:
                queue.put(None)

    await checkpoint()
    task = await curio.current_task()
    queue = curio.UniversalQueue(maxsize=1)
    finish_event = curio.Event()
    retval, exception = None, None
    limiter = limiter or _default_thread_limiter
    await limiter.acquire_on_behalf_of(task)
    thread = Thread(target=thread_worker, daemon=True)
    helper_task = await curio.spawn(async_call_helper, daemon=True)
    thread.start()
    async with CancelScope(shield=not cancellable):
        await finish_event.wait()

    if exception is not None:
        raise exception
    else:
        return cast(T_Retval, retval)


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    future: Future[T_Retval] = Future()
    threadlocals.queue.put((func, args, future))
    return future.result()


class BlockingPortal(abc.BlockingPortal):
    __slots__ = '_queue'

    def __init__(self):
        super().__init__()
        self._queue = curio.UniversalQueue()

    async def _process_queue(self) -> None:
        while self._event_loop_thread_id or not self._queue.empty():
            func, args, future = await self._queue.get()
            if func is not None:
                await self._task_group.spawn(self._call_func, func, args, future)

    async def __aenter__(self) -> 'BlockingPortal':
        await super().__aenter__()
        await self._task_group.spawn(self._process_queue)
        return self

    async def stop(self, cancel_remaining: bool = False) -> None:
        if self._event_loop_thread_id is None:
            return

        await super().stop(cancel_remaining)

        # Wake up from queue.get()
        await self._queue.put((None, None, None))

    def _spawn_task_from_thread(self, func: Callable, args: tuple, future: Future) -> None:
        self._queue.put((func, args, future))


#
# Subprocesses
#

class FileStreamWrapper(abc.ByteStream):
    def __init__(self, stream: curio.io.FileStream):
        super().__init__()
        self._stream = stream

    async def receive(self, max_bytes: Optional[int] = None) -> bytes:
        data = await self._stream.read(max_bytes or 65536)
        if data:
            return data
        else:
            raise EndOfStream

    async def send(self, item: bytes) -> None:
        await self._stream.write(item)

    async def send_eof(self) -> None:
        raise NotImplementedError

    async def aclose(self) -> None:
        await self._stream.close()


@dataclass
class Process(abc.Process):
    _process: curio.subprocess.Popen
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
    process = curio.subprocess.Popen(command, stdin=stdin, stdout=stdout, stderr=stderr,
                                     shell=shell)
    stdin_stream = FileStreamWrapper(process.stdin) if process.stdin else None
    stdout_stream = FileStreamWrapper(process.stdout) if process.stdout else None
    stderr_stream = FileStreamWrapper(process.stderr) if process.stderr else None
    return Process(process, stdin_stream, stdout_stream, stderr_stream)


#
# Sockets and networking
#

_reader_tasks: Dict[socket.SocketType, curio.Task] = {}
_writer_tasks: Dict[socket.SocketType, curio.Task] = {}


class _CurioSocketMixin(Generic[T_SockAddr]):
    def __init__(self, curio_socket: curio.io.Socket):
        self._curio_socket = curio_socket
        self._closed = False

    @property
    def _raw_socket(self) -> socket.socket:
        return self._curio_socket._socket

    async def aclose(self) -> None:
        if self._curio_socket.fileno() >= 0:
            self._closed = True
            rtask, wtask = await curio.traps._io_waiting(self._curio_socket)
            await self._curio_socket.close()
            if rtask:
                await rtask.cancel(blocking=False, exc=ClosedResourceError)
            if wtask:
                await wtask.cancel(blocking=False, exc=ClosedResourceError)

    def _convert_socket_error(self, exc: Union[OSError, AttributeError]) -> NoReturn:
        if self._curio_socket.fileno() < 0 and self._closed:
            raise ClosedResourceError from None
        elif isinstance(exc, OSError):
            raise BrokenResourceError from exc
        else:
            raise exc


class SocketStream(_CurioSocketMixin, abc.SocketStream):
    def __init__(self, curio_socket: curio.io.Socket):
        super().__init__(curio_socket)
        self._receive_guard = ResourceGuard('reading from')
        self._send_guard = ResourceGuard('writing to')

    async def receive(self, max_bytes: int = 65536) -> bytes:
        with self._receive_guard:
            await checkpoint()
            try:
                data = await self._curio_socket.recv(max_bytes)
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)

            if data:
                return data
            else:
                raise EndOfStream

    async def send(self, item: bytes) -> None:
        with self._send_guard:
            await checkpoint()
            try:
                await self._curio_socket.sendall(item)
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)

    async def send_eof(self) -> None:
        await self._curio_socket.shutdown(socket.SHUT_WR)


class SocketListener(_CurioSocketMixin, abc.SocketListener):
    def __init__(self, raw_socket: socket.SocketType):
        super().__init__(curio.io.Socket(raw_socket))
        self._accept_guard = ResourceGuard('accepting connections from')

    async def accept(self) -> SocketStream:
        with self._accept_guard:
            await checkpoint()
            try:
                curio_socket, _addr = await self._curio_socket.accept()
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)

        if curio_socket.family in (socket.AF_INET, socket.AF_INET6):
            curio_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)

        return SocketStream(curio_socket)


class UDPSocket(_CurioSocketMixin[IPSockAddrType], abc.UDPSocket):
    def __init__(self, curio_socket: curio.io.Socket):
        super().__init__(curio_socket)
        self._receive_guard = ResourceGuard('reading from')
        self._send_guard = ResourceGuard('writing to')

    async def receive(self) -> Tuple[bytes, IPSockAddrType]:
        with self._receive_guard:
            await checkpoint()
            try:
                data, addr = await self._curio_socket.recvfrom(65536)
                return data, convert_ipv6_sockaddr(addr)
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)

    async def send(self, item: UDPPacketType) -> None:
        with self._send_guard:
            await checkpoint()
            try:
                await self._curio_socket.sendto(*item)
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)


class ConnectedUDPSocket(_CurioSocketMixin[IPSockAddrType], abc.ConnectedUDPSocket):
    def __init__(self, curio_socket: curio.io.Socket):
        super().__init__(curio_socket)
        self._receive_guard = ResourceGuard('reading from')
        self._send_guard = ResourceGuard('writing to')

    async def receive(self) -> bytes:
        with self._receive_guard:
            await checkpoint()
            try:
                return await self._curio_socket.recv(65536)
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)

    async def send(self, item: bytes) -> None:
        with self._send_guard:
            await checkpoint()
            try:
                await self._curio_socket.send(item)
            except (OSError, AttributeError) as exc:
                self._convert_socket_error(exc)


async def connect_tcp(host: str, port: int,
                      bind_addr: Optional[IPSockAddrType] = None) -> SocketStream:
    curio_socket = await curio.open_connection(host, port, source_addr=bind_addr)
    curio_socket.setsockopt(socket.IPPROTO_TCP, socket.TCP_NODELAY, 1)
    return SocketStream(curio_socket)


async def connect_unix(path: str) -> SocketStream:
    curio_socket = await curio.open_unix_connection(path)
    return SocketStream(curio_socket)


async def create_udp_socket(
    family: socket.AddressFamily,
    local_address: Optional[IPSockAddrType],
    remote_address: Optional[IPSockAddrType],
    reuse_port: bool
) -> Union[UDPSocket, ConnectedUDPSocket]:
    curio_socket = curio.socket.socket(family=family, type=socket.SOCK_DGRAM)

    if reuse_port:
        curio_socket.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEPORT, 1)

    if local_address:
        curio_socket.bind(local_address)

    if remote_address:
        await curio_socket.connect(remote_address)
        return ConnectedUDPSocket(curio_socket)
    else:
        return UDPSocket(curio_socket)


def getaddrinfo(host: Union[bytearray, bytes, str], port: Union[str, int, None], *,
                family: Union[int, AddressFamily] = 0, type: Union[int, SocketKind] = 0,
                proto: int = 0, flags: int = 0) -> Awaitable[GetAddrInfoReturnType]:
    return curio.socket.getaddrinfo(host, port, family, type, proto, flags)


getnameinfo = curio.socket.getnameinfo


async def wait_socket_readable(sock):
    await checkpoint()
    if _reader_tasks.get(sock):
        raise BusyResourceError('reading from') from None

    _reader_tasks[sock] = await curio.current_task()
    try:
        return await curio.traps._read_wait(sock)
    except CancelledError:
        if sock.fileno() == -1:
            raise ClosedResourceError from None
        else:
            raise
    finally:
        del _reader_tasks[sock]


async def wait_socket_writable(sock):
    await checkpoint()
    if _writer_tasks.get(sock):
        raise BusyResourceError('writing to') from None

    _writer_tasks[sock] = await curio.current_task()
    try:
        return await curio.traps._write_wait(sock)
    except CancelledError:
        if sock.fileno() == -1:
            raise ClosedResourceError from None
        else:
            raise
    finally:
        del _writer_tasks[sock]


#
# Synchronization
#

class Lock(abc.Lock):
    def __init__(self):
        self._lock = curio.Lock()

    def locked(self) -> bool:
        return self._lock.locked()

    async def acquire(self) -> None:
        await checkpoint()
        await self._lock.acquire()

    async def release(self) -> None:
        await self._lock.release()


class Condition(abc.Condition):
    def __init__(self, lock: Optional[Lock]):
        curio_lock = lock._lock if lock else None
        self._condition = curio.Condition(curio_lock)

    async def acquire(self) -> None:
        await checkpoint()
        await self._condition.acquire()

    async def release(self) -> None:
        await self._condition.release()

    def locked(self) -> bool:
        return self._condition.locked()

    async def notify(self, n=1):
        await self._condition.notify(n)

    async def notify_all(self):
        await self._condition.notify_all()

    async def wait(self):
        await checkpoint()
        return await self._condition.wait()


class Event(abc.Event):
    def __init__(self):
        self._event = curio.Event()

    async def set(self) -> None:
        await self._event.set()

    def is_set(self) -> bool:
        return self._event.is_set()

    async def wait(self):
        await checkpoint()
        return await self._event.wait()


class Semaphore(abc.Semaphore):
    def __init__(self, value: int):
        self._semaphore = curio.Semaphore(value)

    async def acquire(self) -> None:
        await checkpoint()
        await self._semaphore.acquire()

    async def release(self) -> None:
        await self._semaphore.release()

    @property
    def value(self):
        return self._semaphore.value


class CapacityLimiter(abc.CapacityLimiter):
    def __init__(self, total_tokens: float):
        self._set_total_tokens(total_tokens)
        self._borrowers: Set[Any] = set()
        self._wait_queue: Dict[Any, curio.Event] = OrderedDict()

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
            await event.set()

    @property
    def borrowed_tokens(self) -> int:
        return len(self._borrowers)

    @property
    def available_tokens(self) -> float:
        return self._total_tokens - len(self._borrowers)

    async def acquire_nowait(self):
        await self.acquire_on_behalf_of_nowait(await curio.current_task())

    async def acquire_on_behalf_of_nowait(self, borrower):
        if borrower in self._borrowers:
            raise RuntimeError("this borrower is already holding one of this CapacityLimiter's "
                               "tokens")

        if self._wait_queue or len(self._borrowers) >= self._total_tokens:
            raise WouldBlock

        self._borrowers.add(borrower)

    async def acquire(self):
        return await self.acquire_on_behalf_of(await curio.current_task())

    async def acquire_on_behalf_of(self, borrower):
        try:
            await self.acquire_on_behalf_of_nowait(borrower)
        except WouldBlock:
            event = curio.Event()
            self._wait_queue[borrower] = event
            try:
                await event.wait()
            except BaseException:
                self._wait_queue.pop(borrower, None)
                raise

            self._borrowers.add(borrower)

    async def release(self):
        await self.release_on_behalf_of(await curio.current_task())

    async def release_on_behalf_of(self, borrower):
        try:
            self._borrowers.remove(borrower)
        except KeyError:
            raise RuntimeError("this borrower isn't holding any of this CapacityLimiter's "
                               "tokens") from None

        # Notify the next task in line if this limiter has free capacity now
        if self._wait_queue and len(self._borrowers) < self._total_tokens:
            event = self._wait_queue.popitem()[1]
            await event.set()


def current_default_thread_limiter():
    return _default_thread_limiter


_default_thread_limiter = CapacityLimiter(40)


#
# Operating system signals
#

_signal_queues: DefaultDict[int, List[curio.UniversalQueue]] = defaultdict(list)
_original_signal_handlers:  Dict[int, Any] = {}


def _receive_signal(sig: int, frame) -> None:
    for queue in _signal_queues[sig]:
        queue.put(sig)


async def _iterate_signals(queue: curio.UniversalQueue):
    while True:
        sig = await queue.get()
        yield sig


@asynccontextmanager
async def open_signal_receiver(*signals: int):
    queue = curio.UniversalQueue()
    await checkpoint()
    try:
        for sig in signals:
            _signal_queues[sig].append(queue)
            previous_handler = signal(sig, _receive_signal)
            if sig not in _original_signal_handlers:
                _original_signal_handlers[sig] = previous_handler

        gen = _iterate_signals(queue)
        yield gen
    finally:
        await gen.aclose()

        for sig in signals:
            try:
                del _signal_queues[sig]
            except ValueError:
                pass

            if not _signal_queues[sig]:
                previous_handler = _original_signal_handlers.pop(sig)
                signal(sig, previous_handler)
                del _signal_queues[sig]


#
# Testing and debugging
#

async def get_current_task() -> TaskInfo:
    task = await curio.current_task()
    return TaskInfo(task.id, task.parentid, task.name, task.coro)


async def get_running_tasks() -> List[TaskInfo]:
    task_infos = []
    kernel = await curio.traps._get_kernel()
    for task in kernel._tasks.values():
        if not task.terminated:
            task_infos.append(TaskInfo(task.id, task.parentid, task.name, task.coro))

    return task_infos


async def wait_all_tasks_blocked() -> None:
    this_task = await curio.current_task()
    kernel = await curio.traps._get_kernel()
    while True:
        for task in kernel._tasks.values():
            if task.id == this_task.id:
                continue

            # Consider any task doing sleep(0) as not being blocked
            awaitable = task.coro.cr_await
            while inspect.iscoroutine(awaitable) and hasattr(awaitable, 'cr_code'):
                if (awaitable.cr_code is curio.sleep.__code__
                        and awaitable.cr_frame.f_locals['seconds'] == 0):
                    awaitable = None
                elif awaitable.cr_await:
                    awaitable = awaitable.cr_await
                else:
                    break

            if awaitable is None:
                await curio.sleep(0)
                break
        else:
            return


class TestRunner(abc.TestRunner):
    def __init__(self, **options):
        self._kernel = curio.Kernel(**options)

    def close(self) -> None:
        self._kernel.run(shutdown=True)

    def call(self, func: Callable[..., Awaitable], *args, **kwargs):
        async def call():
            # This wrapper is needed because curio kernels cannot run() the asend() method of async
            # generators because it's neither a coroutine object or a coroutine function
            return await func(*args, **kwargs)

        return self._kernel.run(call)
