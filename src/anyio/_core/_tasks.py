from __future__ import annotations

import math
import sys
from collections import deque
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Callable,
    Coroutine,
    Generator,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    asynccontextmanager,
    contextmanager,
)
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ..abc._tasks import TaskGroup, TaskStatus
from ._contextmanagers import AsyncContextManagerMixin
from ._eventloop import get_async_backend, get_cancelled_exc_class
from ._exceptions import EndOfStream

if sys.version_info >= (3, 11):
    from typing import Self, TypeVarTuple, Unpack
else:
    from typing_extensions import Self, TypeVarTuple, Unpack

if TYPE_CHECKING:
    from ..streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from ._synchronization import CapacityLimiter, RateLimiter

T = TypeVar("T")
TRetval = TypeVar("TRetval")
PosArgsT = TypeVarTuple("PosArgsT")


class _IgnoredTaskStatus(TaskStatus[object]):
    def started(self, value: object = None) -> None:
        pass


TASK_STATUS_IGNORED = _IgnoredTaskStatus()


class CancelScope:
    """
    Wraps a unit of work that can be made separately cancellable.

    :param deadline: The time (clock value) when this scope is cancelled automatically
    :param shield: ``True`` to shield the cancel scope from external cancellation
    """

    def __new__(
        cls, *, deadline: float = math.inf, shield: bool = False
    ) -> CancelScope:
        return get_async_backend().create_cancel_scope(shield=shield, deadline=deadline)

    def cancel(self, reason: str | None = None) -> None:
        """
        Cancel this scope immediately.

        :param reason: a message describing the reason for the cancellation

        """
        raise NotImplementedError

    @property
    def deadline(self) -> float:
        """
        The time (clock value) when this scope is cancelled automatically.

        Will be ``float('inf')`` if no timeout has been set.

        """
        raise NotImplementedError

    @deadline.setter
    def deadline(self, value: float) -> None:
        raise NotImplementedError

    @property
    def cancel_called(self) -> bool:
        """``True`` if :meth:`cancel` has been called."""
        raise NotImplementedError

    @property
    def cancelled_caught(self) -> bool:
        """
        ``True`` if this scope suppressed a cancellation exception it itself raised.

        This is typically used to check if any work was interrupted, or to see if the
        scope was cancelled due to its deadline being reached. The value will, however,
        only be ``True`` if the cancellation was triggered by the scope itself (and not
        an outer scope).

        """
        raise NotImplementedError

    @property
    def shield(self) -> bool:
        """
        ``True`` if this scope is shielded from external cancellation.

        While a scope is shielded, it will not receive cancellations from outside.

        """
        raise NotImplementedError

    @shield.setter
    def shield(self, value: bool) -> None:
        raise NotImplementedError

    def __enter__(self) -> CancelScope:
        raise NotImplementedError

    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        raise NotImplementedError


@contextmanager
def fail_after(
    delay: float | None, shield: bool = False
) -> Generator[CancelScope, None, None]:
    """
    Create a context manager which raises a :class:`TimeoutError` if does not finish in
    time.

    :param delay: maximum allowed time (in seconds) before raising the exception, or
        ``None`` to disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a context manager that yields a cancel scope
    :rtype: :class:`~typing.ContextManager`\\[:class:`~anyio.CancelScope`\\]

    """
    current_time = get_async_backend().current_time
    deadline = (current_time() + delay) if delay is not None else math.inf
    with get_async_backend().create_cancel_scope(
        deadline=deadline, shield=shield
    ) as cancel_scope:
        yield cancel_scope

    if cancel_scope.cancelled_caught and current_time() >= cancel_scope.deadline:
        raise TimeoutError


def move_on_after(delay: float | None, shield: bool = False) -> CancelScope:
    """
    Create a cancel scope with a deadline that expires after the given delay.

    :param delay: maximum allowed time (in seconds) before exiting the context block, or
        ``None`` to disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a cancel scope

    """
    deadline = (
        (get_async_backend().current_time() + delay) if delay is not None else math.inf
    )
    return get_async_backend().create_cancel_scope(deadline=deadline, shield=shield)


def current_effective_deadline() -> float:
    """
    Return the nearest deadline among all the cancel scopes effective for the current
    task.

    :return: a clock value from the event loop's internal clock (or ``float('inf')`` if
        there is no deadline in effect, or ``float('-inf')`` if the current scope has
        been cancelled)
    :rtype: float

    """
    return get_async_backend().current_effective_deadline()


def create_task_group() -> TaskGroup:
    """
    Create a task group.

    :return: a task group

    """
    return get_async_backend().create_task_group()


class AwaitedTaskTerminated(Exception):
    """
    Raised when awaiting on a :class:`TaskHandle` which was terminated by a
    `BaseException`.

    This exception class exists because a :exc:`BaseException` (i.e. one
    that is not an :exc:`Exception`) should not be suppressed, nor
    forwarded to another scope.
    """


class AwaitedTaskCancelled(AwaitedTaskTerminated):
    """
    Raised when awaiting on a :class:`TaskHandle` which was cancelled.

    This subclass of :exc:`AwaitedTaskTerminated` exists in order to
    differentiate between the cancellation of the host task (the one
    awaiting on a task) and the cancellation of the task it's awaiting on.

    Additionally, raising :class:`asyncio.CancelledError` when waiting on
    a task would potentially cause cancellation counters (Python 3.11 and later) to
    be incorrectly decremented, as they should only be decremented when the task
    itself has been cancelled.
    """


class TaskHandle(Generic[T]):
    """
    Returned from task-spawning methods in :class:`EnhancedTaskGroup`. Can be awaited on
    to get the return value of the task (or the raised exception). If the task was
    terminated by a :exc:`BaseException`, :exc:`AwaitedTaskTerminated` will be raised
    (or its subclass :exc:`AwaitedTaskCancelled` if the task was cancelled).
    """

    __slots__ = (
        "__weakref__",
        "_cancel_scope",
        "_name",
        "_event",
        "_return_value",
        "_exception",
        "_start_value",
        "_awaited",
    )

    _return_value: T
    _start_value: Any

    def __init__(self, name: str | None) -> None:
        from ._synchronization import Event

        self._cancel_scope: CancelScope = CancelScope()
        self._name = name
        self._event = Event()
        self._exception: BaseException | None = None
        self._awaited = False

    def set_return_value(self, value: T) -> None:
        self._return_value = value
        self._event.set()

    def set_exception(self, exception: BaseException) -> None:
        if not isinstance(exception, Exception):
            exc = (
                AwaitedTaskCancelled
                if isinstance(exception, get_cancelled_exc_class())
                else AwaitedTaskTerminated
            )(f"the task being awaited on ({self.name!r}) was cancelled")
            exc.__cause__ = exception
            exception = exc

        self._exception = exception
        self._event.set()

    def cancel(self) -> None:
        self._cancel_scope.cancel()

    @property
    def cancelled(self) -> bool:
        return self._cancel_scope.cancel_called or isinstance(
            self._exception, get_cancelled_exc_class()
        )

    @property
    def name(self) -> str | None:
        return self._name

    @property
    def exception(self) -> BaseException | None:
        return self._exception

    @property
    def start_value(self) -> Any:
        try:
            return self._start_value
        except AttributeError:
            raise ValueError(
                "this task handle has no start value (the task was not started with "
                "'await tg.start(...)`)"
            ) from None

    def __await__(self) -> Generator[Any, None, T]:
        if self._awaited:
            raise RuntimeError(
                f"{self.__class__.__qualname__} cannot be awaited multiple times"
            )

        self._awaited = True
        if not self._event.is_set():
            try:
                yield from self._event.wait().__await__()
            except BaseException:
                self._awaited = False
                raise

        if self._exception is not None:
            try:
                raise self._exception
            finally:
                del self._exception

        try:
            return self._return_value
        finally:
            del self._return_value

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__} name={self.name!r}>"


class EnhancedTaskGroup:
    async def __aenter__(self) -> Self:
        self._tasks: dict[Coroutine[Any, Any, Any], TaskHandle[Any]] = {}
        self._task_group = create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

    async def _run_coro(
        self, coro: Coroutine[Any, Any, T], handle: TaskHandle[T]
    ) -> None:
        __tracebackhide__ = True
        with handle._cancel_scope:
            try:
                retval = await coro
            except BaseException as exc:
                handle.set_exception(exc)
                raise
            else:
                handle.set_return_value(retval)
                del retval
            finally:
                del self._tasks[coro]

    async def _run_start_func(
        self,
        func: Callable[..., Coroutine[Any, Any, T]],
        args: tuple[Any],
        kwargs: Mapping[str, Any],
        handle: TaskHandle[T],
        *,
        task_status: TaskStatus[Any],
    ) -> None:
        __tracebackhide__ = True
        coro = func(*args, task_status=task_status, **kwargs)
        self._tasks[coro] = handle
        with handle._cancel_scope:
            try:
                retval = await coro
            except BaseException as exc:
                handle.set_exception(exc)
                raise
            else:
                handle.set_return_value(retval)
            finally:
                del self._tasks[coro]

    @property
    def cancel_scope(self) -> CancelScope:
        return self._task_group.cancel_scope

    async def start(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, T]],
        /,
        *args: Unpack[PosArgsT],
        name: str | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> TaskHandle[T]:
        handle = TaskHandle[T](name)
        handle._start_value = await self._task_group.start(
            self._run_start_func, func, args, kwargs or {}, handle
        )
        return handle

    def start_soon(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, T]],
        /,
        *args: Unpack[PosArgsT],
        name: str | None = None,
        kwargs: Mapping[str, Any] | None = None,
    ) -> TaskHandle[T]:
        coro = func(*args, **(kwargs or {}))
        return self.create_task(coro, name=name)

    def create_task(
        self, coro: Coroutine[Any, Any, T], /, *, name: str | None = None
    ) -> TaskHandle[T]:
        handle = TaskHandle[T](name)
        self._tasks[coro] = handle
        self._task_group.start_soon(self._run_coro, coro, handle, name=name)
        return handle

    def cancel_all(self) -> None:
        """
        Cancel all currently running child tasks.

        This method does **not** cancel the host task.

        """
        for task in self._tasks.values():
            task.cancel()


class AsyncResultsIterator(AsyncContextManagerMixin):
    _coros: deque[Coroutine[Any, Any, Any]]
    _task_group: EnhancedTaskGroup
    _receive: MemoryObjectReceiveStream[TaskHandle]

    def __init__(
        self,
        coros: Iterable[Coroutine[Any, Any, Any]],
        concurrency_limiter: CapacityLimiter | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._tasks: dict[Coroutine[Any, Any, Any], TaskHandle[Any]] = {}
        self._coros = deque(coros)
        self._concurrency_limiter = concurrency_limiter
        self._rate_limiter = rate_limiter

    def cancel_all(self) -> None:
        """Cancel all the currently running tasks within this result iterator."""
        self._task_group.cancel_all()
        self._clear_coros()

    def _clear_coros(self) -> None:
        for coro in self._coros:
            coro.close()

        self._coros.clear()

    async def _run_task(
        self, coro: Coroutine[Any, Any, Any], send: MemoryObjectSendStream[TaskHandle]
    ) -> Any:
        try:
            return await coro
        finally:
            send.send_nowait(self._tasks[coro])
            send.close()
            del self._tasks[coro]
            if self._concurrency_limiter is not None:
                self._concurrency_limiter.release_on_behalf_of(coro)

    async def _feed_tasks(self, send: MemoryObjectSendStream[TaskHandle]) -> None:
        tasks_spawned = 0
        with send:
            while self._coros:
                coro = self._coros.popleft()
                try:
                    # Apply concurrency limit
                    if self._concurrency_limiter is not None:
                        await self._concurrency_limiter.acquire_on_behalf_of(coro)

                    # Apply rate limit
                    if self._rate_limiter is not None:
                        await self._rate_limiter.acquire()
                except BaseException:
                    coro.close()
                    raise

                self._tasks[coro] = self._task_group.create_task(
                    self._run_task(coro, send.clone()),
                    name=f"Task {tasks_spawned} of result iterator {id(self):x}",
                )
                tasks_spawned += 1

    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        from anyio import create_memory_object_stream

        async with AsyncExitStack() as exit_stack:
            exit_stack.callback(self._clear_coros)
            send, self._receive = create_memory_object_stream[TaskHandle](
                len(self._coros)
            )
            exit_stack.enter_context(self._receive)
            self._task_group = await exit_stack.enter_async_context(EnhancedTaskGroup())
            self._task_group.start_soon(self._feed_tasks, send)
            yield self

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TaskHandle[Any]:
        try:
            return await self._receive.receive()
        except EndOfStream:
            raise StopAsyncIteration from None


async def amap(
    func: Callable[[T], Coroutine[Any, Any, TRetval]],
    args: Iterable[T],
    *,
    rate_limiter: RateLimiter | None = None,
) -> Sequence[TRetval]:
    """
    Run the given coroutine function concurrently for multiple argument values.

    :param func: a coroutine function that takes a single argument
    :param args: a sequence of argument values to pass to ``func``
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: task results for each argument in the same order as they were passed

    """
    tasks: list[TaskHandle[TRetval]] = []
    async with EnhancedTaskGroup() as tg:
        for arg in args:
            if rate_limiter is not None:
                await rate_limiter.acquire()

            tasks.append(tg.start_soon(func, arg))

    return [await task for task in tasks]


def as_completed(
    coros: Iterable[Coroutine[Any, Any, T]],
    /,
    *,
    concurrency_limiter: CapacityLimiter | None = None,
    rate_limiter: RateLimiter | None = None,
) -> AbstractAsyncContextManager[AsyncIterable[TaskHandle[T]]]:
    """
    Run the given coroutines concurrently in a task group and yield task handles as they
    complete.

    :param coros: an iterable of coroutine objects to run as tasks
    :param concurrency_limiter: a capacity limiter that controls the maximum number of
        tasks running concurrently
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: an async context manager yielding an async iterator that yields task
        handles in the order they finished

    """
    return AsyncResultsIterator(coros, concurrency_limiter, rate_limiter)


async def gather(
    *coros: Coroutine[Any, Any, T],
    rate_limiter: RateLimiter | None = None,
) -> Sequence[T]:
    """
    Run a number of coroutines in a task group and return their results.

    :param coros: coroutine objects to run as tasks
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: a sequence of return values from the coroutines in the same order as they
        were passed

    """
    task_handles: list[TaskHandle[T]] = []
    async with EnhancedTaskGroup() as tg:
        coro_iterator = iter(coros)
        for coro in coro_iterator:
            # Apply task start rate limits, if any
            if rate_limiter is not None:
                await rate_limiter.acquire()

            try:
                task_handles.append(tg.create_task(coro))
            except Exception:
                for coro in coro_iterator:
                    coro.close()

                raise

    return [await handle for handle in task_handles]


async def race(
    *coros: Coroutine[Any, Any, T],
    rate_limiter: RateLimiter | None = None,
) -> T:
    """
    Run the given coroutines concurrently and return the first one to complete.

    When the first task completes, the remaining tasks are cancelled and their results
    are discarded. If any task raises an exception, it is propagated to the caller in an
    exception group.

    :param coros: coroutine objects to run as tasks
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: the return value of the first completed task

    """
    if not coros:
        raise ValueError("race() takes at least one coroutine")

    retval: list[T] = []

    async def helper(coro: Coroutine[Any, Any, T]) -> None:
        local_retval = await coro
        if not retval:
            retval.append(local_retval)
            tg.cancel_all()

    async with EnhancedTaskGroup() as tg:
        coro_iterator = iter(coros)
        for coro in coro_iterator:
            # Apply task start rate limits, if any
            if rate_limiter is not None:
                await rate_limiter.acquire()

            try:
                tg.create_task(helper(coro))
            except Exception:
                for coro in coro_iterator:
                    coro.close()

                raise

    return retval[0]
