from __future__ import annotations

import math
import sys
from collections import deque
from collections.abc import (
    AsyncGenerator,
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
from ._eventloop import current_time, get_async_backend, get_cancelled_exc_class, sleep

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


class AwaitedTaskCancelled(Exception):
    """
    Raised when awaiting on a :class:`TaskHandle` which was cancelled.

    This exception class exists in order to differentiate between the cancellation of
    the host task (the one awaiting on a task) and the cancellation of the task it's
    awaiting on. Additionally, raising :class:`asyncio.CancelledError` when waiting on
    a task would potentially cause cancellation`counters (Python 3.11 and later) to
    """


class TaskHandle(Generic[T]):
    """
    Returned from task-spawning methods in :class:`EnhancedTaskGroup`. Can be awaited on
    to get the return value of the task (or the raised exception). If the task was
    cancelled, :exc:`AwaitedTaskCancelled` will be raised.
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
        if isinstance(exception, get_cancelled_exc_class()):
            exc = AwaitedTaskCancelled(
                f"the task being awaited on ({self.name!r}) was cancelled"
            )
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

        if not self._event.is_set():
            yield from self._event.wait().__await__()

        self._awaited = True
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
            finally:
                del self._tasks[coro]
                del retval

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


class AsyncResultsIterator:
    _coros: deque[Coroutine[Any, Any, Any]]
    _task_group: EnhancedTaskGroup
    _semaphore: Semaphore
    _send: MemoryObjectSendStream[TaskHandle]
    _receive: MemoryObjectReceiveStream[TaskHandle]
    _rate: float | None

    def __init__(
        self,
        coros: Iterable[Coroutine[Any, Any, Any]],
        max_at_once: int | None = None,
        max_task_per_second: float | None = None,
    ) -> None:
        from ._streams import create_memory_object_stream
        from ._synchronization import Semaphore

        if max_task_per_second is not None:
            if (
                not isinstance(max_task_per_second, (int, float))
                or max_task_per_second < 0
            ):
                raise ValueError("max_task_per_second must be a positive number")

        self._tasks: dict[Coroutine[Any, Any, Any], TaskHandle[Any]] = {}
        self._coros = deque(coros)
        self._task_group: EnhancedTaskGroup = EnhancedTaskGroup()
        self._send, self._receive = create_memory_object_stream[Any](len(self._coros))
        self._semaphore = Semaphore(max_at_once or len(self._coros), fast_acquire=True)
        self._rate = (
            (1 / max_task_per_second) if max_task_per_second is not None else None
        )

    def cancel_all(self) -> None:
        """Cancel all the currently running tasks within this result iterator."""
        self._task_group.cancel_all()
        self._clear_coros()

    def _clear_coros(self) -> None:
        for coro in self._coros:
            coro.close()

        self._coros.clear()

    async def _run_task(self, coro: Coroutine[Any, Any, Any]) -> Any:
        try:
            return await coro
        finally:
            self._send.send_nowait(self._tasks[coro])
            self._semaphore.release()
            del self._tasks[coro]

    async def _feed_tasks(self) -> None:
        start_time = current_time()
        tasks_spawned = 0
        while self._coros:
            # Apply concurrency limit
            await self._semaphore.acquire()

            # Apply rate limit
            if self._rate is not None:
                next_allowed_time = start_time + self._rate * tasks_spawned
                if delay := max(next_allowed_time - current_time(), 0):
                    await sleep(delay)

            coro = self._coros.popleft()
            self._tasks[coro] = self._task_group.create_task(
                self._run_task(coro),
                name=f"Task {tasks_spawned} of result iterator {id(self):x}",
            )
            tasks_spawned += 1

    async def __aenter__(self) -> Self:
        await self._task_group.__aenter__()
        try:
            self._task_group.start_soon(self._feed_tasks)
        except BaseException as exc:
            await self._task_group.__aexit__(type(exc), exc, exc.__traceback__)
            raise

        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        try:
            return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)
        finally:
            self._send.close()
            self._receive.close()
            self._clear_coros()

    def __aiter__(self) -> Self:
        return self

    async def __anext__(self) -> TaskHandle[Any]:
        if not self._coros and not self._tasks:
            raise StopAsyncIteration

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

    return [await task for task in tasks]


@asynccontextmanager
async def as_completed(
    coros: Iterable[Coroutine[Any, Any, Any]],
    /,
    *,
    max_at_once: int | None = None,
    max_per_second: float | None = None,
) -> AsyncGenerator[AsyncResultsIterator]:
    """
    Run the given coroutines concurrently in a task group and yield task handles as they
    complete.

    :param coros: an iterable of coroutine objects to run as tasks
    :param max_at_once: how many tasks to allow to run at once
    :param max_per_second: how many tasks to allow to be launched per second
    :return: an async context manager yielding an async iterator that yields task
        handles in the order they finished

    """
    async with AsyncResultsIterator(coros, max_at_once, max_per_second) as iterator:
        yield iterator
