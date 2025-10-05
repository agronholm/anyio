from __future__ import annotations

import math
import sys
from asyncio import iscoroutine
from collections import deque
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    Callable,
    Coroutine,
    Generator,
    Iterable,
    Sequence,
)
from contextlib import (
    AbstractAsyncContextManager,
    AsyncExitStack,
    ExitStack,
    asynccontextmanager,
    contextmanager,
)
from contextvars import ContextVar
from inspect import isasyncgen
from operator import delitem
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, overload

from ..abc import TaskGroup, TaskStatus
from ._contextmanagers import AsyncContextManagerMixin
from ._eventloop import get_async_backend, get_cancelled_exc_class
from ._exceptions import EndOfStream, TaskAborted, TaskCancelled

if sys.version_info >= (3, 11):
    from typing import Self, TypeVarTuple
else:
    from typing_extensions import Self, TypeVarTuple

if sys.version_info >= (3, 13):
    from typing import TypeVar
else:
    from typing_extensions import TypeVar

if TYPE_CHECKING:
    from ..streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream
    from ._synchronization import CapacityLimiter, Event, RateLimiter

T = TypeVar("T")
TRetval = TypeVar("TRetval")
TStartval = TypeVar("TStartval", default=None)
PosArgsT = TypeVarTuple("PosArgsT")

_current_task_handle: ContextVar[TaskHandle] = ContextVar("_current_task_handle")


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


class TaskHandle(Generic[T, TStartval]):
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
        "_finished_event",
        "_return_value",
        "_exception",
        "_start_value",
        "_awaited",
    )

    _return_value: T
    _start_value: TStartval

    def __init__(self, name: str | None) -> None:
        from ._synchronization import Event

        self._name = name
        self._cancel_scope = CancelScope()
        self._finished_event = Event()
        self._exception: BaseException | None = None
        self._awaited = False

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
    def start_value(self) -> TStartval:
        try:
            return self._start_value
        except AttributeError:
            raise RuntimeError(
                "this task has no start value (the task was not started with "
                "'await tg.start(...)`)"
            ) from None

    @property
    def return_value(self) -> T:
        try:
            return self._return_value
        except AttributeError:
            if self._exception is not None:
                raise RuntimeError(
                    f"this task raised an exception "
                    f"({self._exception.__class__.__qualname__})"
                ) from None

            raise RuntimeError("this task has not returned yet") from None

    def _set_exception(self, exception: BaseException) -> None:
        if not isinstance(exception, Exception):
            exc = (
                TaskCancelled
                if isinstance(exception, get_cancelled_exc_class())
                else TaskAborted
            )(f"the task being awaited on ({self.name!r}) was cancelled")
            exc.__cause__ = exception
            exception = exc

        self._exception = exception
        self._finished_event.set()

    def _set_return_value(self, val: T) -> None:
        assert self._exception is None
        self._return_value = val
        self._finished_event.set()

    def __await__(self) -> Generator[Any, Any, T]:
        if not self._finished_event.is_set():
            try:
                yield from self._finished_event.wait().__await__()
            except BaseException:
                self._awaited = False
                raise

        if self._exception is not None:
            raise self._exception

        return self._return_value

    def __repr__(self) -> str:
        return f"<{self.__class__.__qualname__} name={self.name!r}>"


class EnhancedTaskGroup:
    async def __aenter__(self) -> Self:
        self._tasks: dict[
            Coroutine[Any, Any, Any] | AsyncGenerator[Any, Any],
            TaskHandle[Any, Any],
        ] = {}
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

    def _create_run_exit_stack(
        self,
        coro_or_asyncgen: Coroutine | AsyncGenerator,
        handle: TaskHandle[Any, Any],
        concurrency_limiter: CapacityLimiter | None,
    ) -> ExitStack:
        exit_stack = ExitStack()
        exit_stack.enter_context(handle._cancel_scope)
        exit_stack.callback(delitem, self._tasks, coro_or_asyncgen)
        if concurrency_limiter is not None:
            exit_stack.callback(
                concurrency_limiter.release_on_behalf_of, coro_or_asyncgen
            )

        token = _current_task_handle.set(handle)
        exit_stack.callback(_current_task_handle.reset, token)
        return exit_stack

    async def _run_coro(
        self,
        coro: Coroutine[Any, Any, T],
        handle: TaskHandle[T, None],
        start_event: Event | None = None,
        capacity_limiter: CapacityLimiter | None = None,
    ) -> None:
        __tracebackhide__ = True
        with self._create_run_exit_stack(coro, handle, capacity_limiter):
            if start_event is not None:
                start_event.set()

            try:
                retval = await coro
            except BaseException as exc:
                handle._set_exception(exc)
                raise
            else:
                handle._set_return_value(retval)
                del retval

    async def _run_asyncgen(
        self,
        asyncgen: AsyncGenerator[T, Any],
        handle: TaskHandle[None, T],
        start_event: Event,
        start_exception_container: list[Exception | None],
        capacity_limiter: CapacityLimiter | None = None,
    ) -> None:
        __tracebackhide__ = True
        with self._create_run_exit_stack(asyncgen, handle, capacity_limiter):
            try:
                handle._start_value = await asyncgen.__anext__()
            except BaseException as exc:
                if isinstance(exc, StopAsyncIteration):
                    exc = RuntimeError(
                        f"the async generator for task {handle.name!r} finished "
                        f"without yielding a start value"
                    )

                start_exception_container[0] = (
                    TaskAborted(exc) if not isinstance(exc, Exception) else exc
                )
                start_event.set()

                # Re-raise base exceptions
                if not isinstance(exc, Exception):
                    raise
            else:
                start_event.set()
                try:
                    await asyncgen.__anext__()
                except StopAsyncIteration:
                    handle._set_return_value(None)
                except BaseException as exc:
                    handle._set_exception(exc)
                    raise
                else:
                    error = RuntimeError(
                        f"the async generator for task {handle.name!r} yielded too "
                        f"many times"
                    )
                    handle._set_exception(error)
                    raise error

    @property
    def cancel_scope(self) -> CancelScope:
        return self._task_group.cancel_scope

    def create_task(
        self,
        coro: Coroutine[Any, Any, T],
        /,
        *,
        name: str | None = None,
    ) -> TaskHandle[T]:
        """
        Create a new task and schedule it to run.

        :param coro: a coroutine object
        :param name: optional name to give the task
        :return: a task handle

        """
        if not iscoroutine(coro):
            raise TypeError(f"expected a coroutine, got {coro.__class__.__qualname__}")

        handle = self._tasks[coro] = TaskHandle[T](name)
        self._task_group.start_soon(self._run_coro, coro, handle, name=name)
        return handle

    @overload
    async def start_task(
        self,
        coro_or_asyncgen: AsyncGenerator[T, Any],
        /,
        *,
        name: str | None = None,
        concurency_limiter: CapacityLimiter | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> TaskHandle[None, T]: ...

    @overload
    async def start_task(
        self,
        coro_or_asyncgen: Coroutine[Any, Any, T],
        /,
        *,
        name: str | None = None,
        concurency_limiter: CapacityLimiter | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> TaskHandle[T]: ...

    async def start_task(
        self,
        coro_or_asyncgen: Coroutine[Any, Any, T] | AsyncGenerator[T, Any],
        /,
        *,
        name: str | None = None,
        concurency_limiter: CapacityLimiter | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> TaskHandle[T] | TaskHandle[None, T]:
        """
        Create a new task and wait until it has started.

        If a coroutine object is given, this call will return as soon as the event loop
        has started running the task, but before the coroutine has been started.

        If an async generator object is given, this call will return once the async
        generator has yielded its start value. The start value is available through the
        ``start_value`` attribute of the returned task handle.

        In all cases, this method first acquires both the concurrency limiter and the
        rate limiter, if given (and in that order), before scheduling the task to run.

        :param coro_or_asyncgen: a coroutine object or an async generator object
        :param name: optional name to give the task
        :param concurency_limiter: a capacity limiter that controls the maximum number
            of tasks allowed to run concurrently
        :param rate_limiter: a rate limiter that controls the rate at which tasks are
            started
        :return: a task handle

        """
        from ._synchronization import Event

        # Acquire the concurrency limiter, and release it in _run_coro() or
        # _run_asyncgen()
        try:
            if concurency_limiter is not None:
                await concurency_limiter.acquire_on_behalf_of(coro_or_asyncgen)

            if rate_limiter is not None:
                try:
                    await rate_limiter.acquire()
                except BaseException:
                    if concurency_limiter is not None:
                        concurency_limiter.release_on_behalf_of(coro_or_asyncgen)

                    raise
        except BaseException:
            if isinstance(coro_or_asyncgen, AsyncGenerator):
                await coro_or_asyncgen.aclose()
            else:
                coro_or_asyncgen.close()

            raise

        start_event = Event()
        handle: TaskHandle[T] | TaskHandle[None, T]
        if isasyncgen(coro_or_asyncgen):
            handle = asyncgen_handle = self._tasks[coro_or_asyncgen] = TaskHandle[
                None, T
            ](name)
            start_exception_container: list[Exception | None] = [None]
            self._task_group.start_soon(
                self._run_asyncgen,
                coro_or_asyncgen,
                asyncgen_handle,
                start_event,
                start_exception_container,
                name=name,
            )
            await start_event.wait()
            if (exc := start_exception_container.pop()) is not None:
                raise exc
        elif iscoroutine(coro_or_asyncgen):
            handle = coro_handle = self._tasks[coro_or_asyncgen] = TaskHandle[T](name)
            coro_handle._start_value = None
            self._task_group.start_soon(
                self._run_coro, coro_or_asyncgen, coro_handle, start_event, name=name
            )
            await start_event.wait()
        else:
            raise TypeError(
                "Expected a coroutine or an async generator, got "
                f"{coro_or_asyncgen.__class__.__qualname__}"
            )

        return handle

    def cancel(self) -> None:
        """
        Cancel all currently running child tasks.

        This method does **not** cancel the host task.

        """
        for task in self._tasks.values():
            task.cancel()


class AsyncResultsIterator(AsyncContextManagerMixin):
    _task_group: EnhancedTaskGroup
    _receive: MemoryObjectReceiveStream[TaskHandle]

    def __init__(
        self,
        coros: Iterable[Coroutine[Any, Any, Any]],
        concurrency_limiter: CapacityLimiter | None = None,
        rate_limiter: RateLimiter | None = None,
    ) -> None:
        self._coros: deque[Coroutine[Any, Any, Any]] = deque(coros)
        self._concurrency_limiter = concurrency_limiter
        self._rate_limiter = rate_limiter

    def cancel(self) -> None:
        """Cancel all the currently running tasks within this result iterator."""
        self._task_group.cancel()
        self._clear_coros()

    def _clear_coros(self) -> None:
        for coro in self._coros:
            coro.close()

        self._coros.clear()

    async def _run_task(
        self, coro: Coroutine[Any, Any, T], send: MemoryObjectSendStream[TaskHandle]
    ) -> T:
        try:
            return await coro
        finally:
            send.send_nowait(_current_task_handle.get())
            if self._concurrency_limiter is not None:
                self._concurrency_limiter.release_on_behalf_of(coro)

    async def _feed_tasks(self, send: MemoryObjectSendStream[TaskHandle]) -> None:
        tasks_spawned = 0
        with send:
            async with EnhancedTaskGroup() as tg:
                while self._coros:
                    coro = self._coros.popleft()
                    try:
                        await tg.start_task(
                            self._run_task(coro, send),
                            name=f"Task {tasks_spawned} of {self}",
                            concurency_limiter=self._concurrency_limiter,
                            rate_limiter=self._rate_limiter,
                        )
                    except BaseException:
                        coro.close()
                        raise

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
            await self._task_group.start_task(self._feed_tasks(send))
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
    concurrency_limiter: CapacityLimiter | None = None,
    rate_limiter: RateLimiter | None = None,
) -> Sequence[TRetval]:
    """
    Run the given coroutine function concurrently for multiple argument values.

    :param func: a coroutine function that takes a single argument
    :param args: a sequence of argument values to pass to ``func``
    :param concurrency_limiter: a capacity limiter that controls the maximum number of
        tasks allowed to run concurrently
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: task results for each argument in the same order as they were passed

    """
    async with EnhancedTaskGroup() as tg:
        tasks = [
            await tg.start_task(
                func(arg),
                concurency_limiter=concurrency_limiter,
                rate_limiter=rate_limiter,
            )
            for arg in args
        ]

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
    concurrency_limiter: CapacityLimiter | None = None,
    rate_limiter: RateLimiter | None = None,
) -> Sequence[T]:
    """
    Run a number of coroutines in a task group and return their results.

    :param coros: coroutine objects to run as tasks
    :param concurrency_limiter: a capacity limiter that controls the maximum number of
        tasks running concurrently
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: a sequence of return values from the coroutines in the same order as they
        were passed

    """
    async with EnhancedTaskGroup() as tg:
        coro_iterator = iter(coros)
        try:
            tasks = [
                await tg.start_task(
                    coro,
                    concurency_limiter=concurrency_limiter,
                    rate_limiter=rate_limiter,
                )
                for coro in coros
            ]
        except BaseException:
            for coro in coro_iterator:
                coro.close()

            raise

    return [await handle for handle in tasks]


async def race(
    *coros: Coroutine[Any, Any, T],
    concurrency_limiter: CapacityLimiter | None = None,
    rate_limiter: RateLimiter | None = None,
) -> T:
    """
    Run the given coroutines concurrently and return the first one to complete.

    When the first task completes, the remaining tasks are cancelled and their results
    are discarded. If any task raises an exception, it is propagated to the caller in an
    exception group.

    :param coros: coroutine objects to run as tasks
    :param concurrency_limiter: a capacity limiter that controls the maximum number of
        tasks running concurrently
    :param rate_limiter: a rate limiter that controls the rate at which tasks are
        started
    :return: the return value of the first completed task

    """
    if not coros:
        raise ValueError("race() takes at least one coroutine")

    retval_container: list[T] = []

    async def helper(coro_: Coroutine[Any, Any, T]) -> None:
        local_retval = await coro_
        if not retval_container:
            retval_container.append(local_retval)
            tg.cancel()

    async with EnhancedTaskGroup() as tg:
        coro_iterator = iter(coros)
        for coro in coro_iterator:
            try:
                await tg.start_task(
                    helper(coro),
                    concurency_limiter=concurrency_limiter,
                    rate_limiter=rate_limiter,
                )
            except BaseException:
                for coro_ in coro_iterator:
                    coro_.close()

                raise

    return retval_container[0]
