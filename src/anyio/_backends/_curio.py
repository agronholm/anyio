import inspect
import math
import socket
from collections import OrderedDict, defaultdict
from concurrent.futures import Future
from functools import partial
from signal import signal
from socket import AddressFamily, SocketKind
from threading import Thread
from types import TracebackType
from typing import (
    Callable, Set, Optional, Coroutine, Any, cast, Dict, List, Sequence, DefaultDict, Type,
    Awaitable, Union)
from weakref import WeakKeyDictionary

import curio.io
import curio.meta
import curio.socket
import curio.ssl
import curio.traps
from async_generator import async_generator, asynccontextmanager, yield_

from .. import abc, T_Retval, claim_worker_thread, TaskInfo, _local, GetAddrInfoReturnType
from ..exceptions import (
    ExceptionGroup as BaseExceptionGroup, ClosedResourceError, ResourceBusyError, WouldBlock)
from .._networking import BaseSocket

if 'report_crash' in inspect.signature(curio.spawn).parameters:
    spawn_kwargs = {'report_crash': False}
else:
    spawn_kwargs = {}


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

finalize = curio.meta.finalize


async def sleep(delay: float):
    await check_cancelled()
    await curio.sleep(delay)


#
# Timeouts and cancellation
#

CancelledError = curio.TaskCancelled


class CancelScope:
    __slots__ = ('_deadline', '_shield', '_parent_scope', '_cancel_called', '_active',
                 '_timeout_task', '_previous_timeout', '_tasks', '_host_task', '_timeout_expired')

    def __init__(self, deadline: float = math.inf, shield: bool = False):
        self._deadline = deadline
        self._shield = shield
        self._parent_scope = None
        self._cancel_called = False
        self._active = False
        self._timeout_task = None
        self._previous_timeout = None
        self._tasks = set()  # type: Set[curio.Task]
        self._host_task = None  # type: Optional[curio.Task]
        self._timeout_expired = False

    async def __aenter__(self):
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
                self._previous_timeout = await curio.traps._set_timeout(self._deadline)

        self._active = True
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        self._active = False
        if self._previous_timeout:
            await curio.traps._unset_timeout(self._previous_timeout)

        if exc_type is curio.errors.TaskTimeout:
            if self._deadline != math.inf and await curio.clock() >= self._deadline:
                self._cancel_called = True
                self._timeout_expired = True
                exc_val = CancelledError().with_traceback(exc_tb)

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

        if exc_val is not None and self._timeout_expired:
            raise exc_val
        else:
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
            elif not cancel_scope._shielded_to(self):
                await cancel_scope._cancel()

    def _shielded_to(self, parent: 'CancelScope') -> bool:
        # Check whether this task or any parent up to (but not including) the "parent" argument is
        # shielded
        cancel_scope = self  # type: Optional[CancelScope]
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


abc.CancelScope.register(CancelScope)


async def check_cancelled():
    try:
        cancel_scope = _task_states[await curio.current_task()].cancel_scope
    except KeyError:
        return

    while cancel_scope:
        if cancel_scope.cancel_called:
            raise CancelledError
        elif cancel_scope.shield:
            return
        else:
            cancel_scope = cancel_scope._parent_scope


@asynccontextmanager
@async_generator
async def fail_after(delay: float, shield: bool):
    deadline = await curio.clock() + delay
    async with CancelScope(deadline, shield) as scope:
        await yield_(scope)

    if scope._timeout_expired:
        raise TimeoutError from None


@asynccontextmanager
@async_generator
async def move_on_after(delay: float, shield: bool):
    deadline = await curio.clock() + delay
    async with CancelScope(deadline=deadline, shield=shield) as scope:
        await yield_(scope)


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


class TaskGroup:
    __slots__ = 'cancel_scope', '_active', '_exceptions'

    def __init__(self) -> None:
        self.cancel_scope = CancelScope()
        self._active = False
        self._exceptions = []  # type: List[BaseException]

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
                await task.wait()

        self._active = False
        if not self.cancel_scope._parent_cancelled():
            exceptions = self._filter_cancellation_errors(self._exceptions)
        else:
            exceptions = self._exceptions

        if len(exceptions) > 1:
            raise ExceptionGroup(exceptions)
        elif exceptions and exceptions[0] is not exc_val:
            raise exceptions[0]

        return ignore_exception

    @staticmethod
    def _filter_cancellation_errors(exceptions: Sequence[BaseException]) -> List[BaseException]:
        filtered_exceptions = []  # type: List[BaseException]
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

        task = await curio.spawn(self._run_wrapped_task, func, args, daemon=True, **spawn_kwargs)
        task.parentid = (await curio.current_task()).id
        task.name = name or get_callable_name(func)

        # Make the spawned task inherit the task group's cancel scope
        _task_states[task] = TaskState(cancel_scope=self.cancel_scope)
        self.cancel_scope._tasks.add(task)


abc.TaskGroup.register(TaskGroup)


#
# Threads
#

async def run_in_thread(func: Callable[..., T_Retval], *args, cancellable: bool = False,
                        limiter: Optional['CapacityLimiter'] = None) -> T_Retval:
    async def async_call_helper():
        while True:
            item = await queue.get()
            if item is None:
                await limiter.release_on_behalf_of(task)
                await finish_event.set()
                return

            func_, args_, f = item  # type: Callable, tuple, Future
            try:
                retval_ = await func_(*args_)
            except BaseException as exc_:
                f.set_exception(exc_)
            else:
                f.set_result(retval_)

    def thread_worker():
        nonlocal retval, exception
        try:
            with claim_worker_thread('curio'):
                _local.queue = queue
                retval = func(*args)
        except BaseException as exc:
            exception = exc
        finally:
            if not helper_task.cancelled:
                queue.put(None)

    await check_cancelled()
    task = await curio.current_task()
    queue = curio.UniversalQueue(maxsize=1)
    finish_event = curio.Event()
    retval, exception = None, None
    limiter = limiter or _default_thread_limiter
    await limiter.acquire_on_behalf_of(task)
    thread = Thread(target=thread_worker, daemon=True)
    helper_task = await curio.spawn(async_call_helper, daemon=True, **spawn_kwargs)
    thread.start()
    async with CancelScope(shield=not cancellable):
        await finish_event.wait()

    if exception is not None:
        raise exception
    else:
        return cast(T_Retval, retval)


def run_async_from_thread(func: Callable[..., T_Retval], *args) -> T_Retval:
    future = Future()  # type: Future[T_Retval]
    _local.queue.put((func, args, future))
    return future.result()


#
# Async file I/O
#

async def aopen(*args, **kwargs):
    fp = await run_in_thread(partial(open, *args, **kwargs))
    return curio.file.AsyncFile(fp)


#
# Sockets and networking
#

_reader_tasks = {}  # type: Dict[socket.SocketType, curio.Task]
_writer_tasks = {}  # type: Dict[socket.SocketType, curio.Task]


class Socket(BaseSocket):
    __slots__ = ()

    def _wait_readable(self):
        return wait_socket_readable(self._raw_socket)

    def _wait_writable(self):
        return wait_socket_writable(self._raw_socket)

    def _notify_close(self):
        return notify_socket_close(self._raw_socket)

    def _check_cancelled(self) -> Coroutine[Any, Any, None]:
        return sleep(0)

    def _run_in_thread(self, func: Callable, *args):
        return run_in_thread(func, *args)


def getaddrinfo(host: Union[bytearray, bytes, str], port: Union[str, int, None], *,
                family: Union[int, AddressFamily] = 0, type: Union[int, SocketKind] = 0,
                proto: int = 0, flags: int = 0) -> Awaitable[GetAddrInfoReturnType]:
    return curio.socket.getaddrinfo(host, port, family, type, proto, flags)


getnameinfo = curio.socket.getnameinfo


async def wait_socket_readable(sock):
    await check_cancelled()
    if _reader_tasks.get(sock):
        raise ResourceBusyError('reading from') from None

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
    await check_cancelled()
    if _writer_tasks.get(sock):
        raise ResourceBusyError('writing to') from None

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


async def notify_socket_close(sock: socket.SocketType):
    for tasks_map in _reader_tasks, _writer_tasks:
        task = tasks_map.get(sock)
        if task is not None:
            await task.cancel(blocking=False)


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

    def __aiter__(self):
        return self

    async def __anext__(self):
        await check_cancelled()
        return await super().get()


class CapacityLimiter:
    def __init__(self, total_tokens: float):
        self._set_total_tokens(total_tokens)
        self._borrowers = set()  # type: Set[Any]
        self._wait_queue = OrderedDict()  # type: Dict[Any, curio.Event]

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

abc.Lock.register(Lock)
abc.Condition.register(Condition)
abc.Event.register(Event)
abc.Semaphore.register(Semaphore)
abc.Queue.register(Queue)
abc.CapacityLimiter.register(CapacityLimiter)


#
# Operating system signals
#

_signal_queues = defaultdict(list)  # type: DefaultDict[int, List[curio.UniversalQueue]]
_original_signal_handlers = {}  # type:  Dict[int, Any]


def _receive_signal(sig: int, frame) -> None:
    for queue in _signal_queues[sig]:
        queue.put(sig)


@async_generator
async def _iterate_signals(queue: curio.UniversalQueue):
    while True:
        sig = await queue.get()
        await yield_(sig)


@asynccontextmanager
@async_generator
async def receive_signals(*signals: int):
    queue = curio.UniversalQueue()
    try:
        for sig in signals:
            _signal_queues[sig].append(queue)
            previous_handler = signal(sig, _receive_signal)
            if sig not in _original_signal_handlers:
                _original_signal_handlers[sig] = previous_handler

        gen = _iterate_signals(queue)
        await yield_(gen)
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
                if (awaitable.cr_code is sleep.__code__
                        and awaitable.cr_frame.f_locals['delay'] == 0):
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
