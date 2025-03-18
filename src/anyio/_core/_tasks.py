from __future__ import annotations

import math
import sys
from collections import deque
from collections.abc import (
    AsyncIterator,
    Callable,
    Coroutine,
    Generator,
    Iterable,
    Mapping,
    Sequence,
)
from contextlib import asynccontextmanager, contextmanager
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

from ..abc._tasks import TaskGroup, TaskStatus
from ._eventloop import current_time, get_async_backend, sleep

if sys.version_info >= (3, 11):
    from typing import Self, TypeVarTuple, Unpack
else:
    from typing_extensions import Self, TypeVarTuple, Unpack

if TYPE_CHECKING:
    from ..streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from ._synchronization import Semaphore

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

    def cancel(self) -> None:
        """Cancel this scope immediately."""
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


class TaskHandle(Generic[T]):
    __slots__ = (
        "cancel_scope",
        "_event",
        "_return_value",
        "_exception",
        "_start_value",
    )

    _return_value: T
    _start_value: Any

    def __init__(self) -> None:
        from ._synchronization import Event

        self.cancel_scope: CancelScope = CancelScope()
        self._event = Event()
        self._exception: BaseException | None = None

    def set_return_value(self, value: T) -> None:
        self._return_value = value
        self._event.set()

    def set_exception(self, exception: BaseException) -> None:
        self._exception = exception
        self._event.set()

    def cancel(self) -> None:
        self.cancel_scope.cancel()

    @property
    def start_value(self) -> Any:
        try:
            return self._start_value
        except AttributeError:
            raise ValueError(
                "this task handle has no start value (the task was not started with "
                "'await tg.start(...)`)"
            )

    async def wait(self) -> T:
        await self._event.wait()
        if self._exception is not None:
            raise self._exception

        return self._return_value


class EnhancedTaskGroup:
    async def __aenter__(self) -> Self:
        self._task_group = create_task_group()
        await self._task_group.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

    @staticmethod
    async def _run_coro(coro: Coroutine[Any, Any, T], handle: TaskHandle[T]) -> None:
        __tracebackhide__ = True
        with handle.cancel_scope:
            try:
                retval = await coro
            except BaseException as exc:
                handle.set_exception(exc)
            else:
                handle.set_return_value(retval)

    @staticmethod
    async def _run_start_func(
        func: Callable[..., Coroutine[Any, Any, T]],
        args: tuple[Any],
        kwargs: Mapping[str, Any],
        handle: TaskHandle[T],
        *,
        task_status: TaskStatus[Any],
    ) -> None:
        __tracebackhide__ = True
        with handle.cancel_scope:
            try:
                retval = await func(*args, task_status=task_status, **kwargs)
            except BaseException as exc:
                handle.set_exception(exc)
            else:
                handle.set_return_value(retval)

    async def start(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, T]],
        /,
        *args: Unpack[PosArgsT],
        kwargs: Mapping[str, Any] | None = None,
    ) -> TaskHandle[T]:
        handle = TaskHandle[T]()
        handle._start_value = await self._task_group.start(
            self._run_start_func, func, args, kwargs or {}, handle
        )
        return handle

    def start_soon(
        self,
        func: Callable[[Unpack[PosArgsT]], Coroutine[Any, Any, T]],
        /,
        *args: Unpack[PosArgsT],
        kwargs: Mapping[str, Any] | None = None,
    ) -> TaskHandle[T]:
        coro = func(*args, **(kwargs or {}))
        return self.create_task(coro)

    def create_task(self, coro: Coroutine[Any, Any, T], /) -> TaskHandle[T]:
        handle = TaskHandle[T]()
        self._task_group.start_soon(self._run_coro, coro, handle)
        return handle

    def cancel_all(self) -> None:
        self._task_group.cancel_scope.cancel()


class _ResultsIterator(Generic[TRetval]):
    _coros: deque[Coroutine[Any, Any, TRetval]]
    _task_group: TaskGroup
    _semaphore: Semaphore
    _send: MemoryObjectSendStream[TRetval]
    _receive: MemoryObjectReceiveStream[TRetval]
    _rate: float | None

    def __init__(
        self,
        coros: Iterable[Coroutine[Any, Any, TRetval]],
        max_at_once: int | None = None,
        max_task_per_second: float | None = None,
    ) -> None:
        from ._streams import create_memory_object_stream
        from ._synchronization import Semaphore

        if not isinstance(max_task_per_second, int) or max_task_per_second < 0:
            raise ValueError("max_task_per_second must be a positive integer")

        self._coros = deque(coros)
        self._task_group: TaskGroup = create_task_group()
        self._send, self._receive = create_memory_object_stream[TRetval]()
        self._semaphore = Semaphore(max_at_once or len(self._coros), fast_acquire=True)
        self._rate = (
            (1 / max_task_per_second) if max_task_per_second is not None else None
        )

    def cancel(self) -> None:
        self._task_group.cancel_scope.cancel()

    async def _run_task(self, coro: Coroutine[Any, Any, TRetval]) -> None:
        try:
            retval = await coro
        finally:
            self._semaphore.release()

        await self._send.send(retval)

    async def _feed_tasks(self) -> None:
        start_time = current_time()
        tasks_spawned = 0
        while self._coros:
            # Apply concurrency limit
            await self._semaphore.acquire()

            # Apply rate limit
            if self._rate is not None:
                next_allowed_time = start_time + self._rate * (tasks_spawned + 1)
                if delay := max(next_allowed_time - current_time(), 0):
                    await sleep(delay)

            self._task_group.start_soon(self._run_task, self._coros.popleft())
            tasks_spawned += 1

    async def __aenter__(self) -> Self:
        await self._task_group.__aenter__()
        self._task_group.start_soon(self._feed_tasks)
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        try:
            await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            self._send.close()
            self._receive.close()
            for coro in self._coros:
                coro.close()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TRetval:
        return await self._receive.receive()


async def amap(
    func: Callable[[T], Coroutine[Any, Any, TRetval]],
    args: Iterable[T],
) -> Sequence[TRetval]:
    """
    Run the given coroutine function concurrently for multiple argument values.

    :param func: a coroutine function that takes a single argument
    :param args: a sequence of argument values to pass to ``func``
    :return: task results for each argument in the same order as they were passed

    """
    async with EnhancedTaskGroup() as tg:
        tasks = [tg.start_soon(func, arg) for arg in args]

    return [await task.wait() for task in tasks]


@asynccontextmanager
async def as_completed(
    coros: Iterable[Coroutine[Any, Any, Any]],
    /,
    *,
    max_at_once: int | None = None,
    max_per_second: int | None = None,
) -> AsyncIterator[AsyncIterator[TaskHandle]]:
    """
    Run the given coroutines concurrently in a task group and yield task handles as they
    complete.

    :param coros: an iterable of coroutine objects to run as tasks
    :param max_at_once: how many tasks to allow to run at once
    :param max_per_second: how many tasks to allow to be launched per second
    :return: an async context manager yielding an async iterator that yields task
        handles in the order they finished

    """
    async with _ResultsIterator(coros, max_at_once, max_per_second) as iterator:
        yield iterator
