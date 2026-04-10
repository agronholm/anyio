from __future__ import annotations

import math
import sys
from collections.abc import (
    Coroutine,
    Generator,
)
from contextlib import (
    contextmanager,
)
from contextvars import ContextVar
from enum import Enum, auto
from types import TracebackType
from typing import Any, Generic, TypeVar, final

from ..abc import TaskGroup, TaskStatus
from ._eventloop import get_async_backend, get_cancelled_exc_class
from ._exceptions import TaskCancelled, TaskError
from ._testing import get_current_task

if sys.version_info >= (3, 11):
    from typing import TypeVarTuple
else:
    from typing_extensions import TypeVarTuple

T = TypeVar("T")
T_co = TypeVar("T_co", covariant=True)
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
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread
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
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread

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
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread

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
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread

    """
    return get_async_backend().current_effective_deadline()


def create_task_group() -> TaskGroup:
    """
    Create a task group.

    :return: a task group
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread

    """
    return get_async_backend().create_task_group()


@final
class TaskHandle(Generic[T_co]):
    """
    Returned from :meth:`TaskGroup.create_task() <.abc.TaskGroup.create_task>`.
    Can be awaited on to get the return value of the task (or the raised exception).
    If the task was terminated by a :exc:`BaseException`, :exc:`TaskAborted` will be
    raised (or its subclass :exc:`TaskCancelled` if the task was cancelled).

    .. versionadded:: 4.14.0
    """

    class Status(Enum):
        """
        The status of a task handle.

        .. attribute:: PENDING

            The task has not finished yet.
        .. attribute:: FINISHED

            The task has finished with a return value.
        .. attribute:: CANCELLING

            The task has been cancelled but has not finished yet.
        .. attribute:: CANCELLED

            The task was cancelled and has finished since.
        .. attribute:: ERRORED

            The task raised an exception.
        """

        PENDING = auto()
        FINISHED = auto()
        CANCELLING = auto()
        CANCELLED = auto()
        ERRORED = auto()

    __slots__ = (
        "__weakref__",
        "_coro",
        "_name",
        "_cancel_scope",
        "_finished_event",
        "_return_value",
        "_exception",
        "_status",
    )

    _return_value: T_co

    def __init__(self, coro: Coroutine[Any, Any, T_co], name: str | None) -> None:
        from ._synchronization import Event

        self._coro = coro
        self._cancel_scope = CancelScope()
        self._finished_event = Event()
        self._name = name or coro.__name__
        self._exception: BaseException | None = None
        self._status = TaskHandle.Status.PENDING

    async def _run_coro(self) -> None:
        __tracebackhide__ = True
        if self._name is None:
            self._name = get_current_task().name

        with self._cancel_scope:
            try:
                retval = await self._coro
            except get_cancelled_exc_class():
                self._status = TaskHandle.Status.CANCELLED
            except BaseException as exc:
                self._exception = exc
                self._status = TaskHandle.Status.ERRORED
                raise
            else:
                self._return_value = retval
                self._status = TaskHandle.Status.FINISHED
            finally:
                self._finished_event.set()

    def cancel(self) -> None:
        """
        Set the task to a cancelled state.

        This will interrupt any interruptible asynchronous operation, and will cause
        any further awaits on this task to get immediately cancelled, unless done in
        a shielded cancel scope.

        If the task has already finished, this method has no effect.

        """
        if self._status is TaskHandle.Status.PENDING:
            self._status = TaskHandle.Status.CANCELLING
            self._cancel_scope.cancel()

    @property
    def coro(self) -> Coroutine[Any, Any, T_co]:
        """The coroutine object that was passed to :meth:`TaskGroup.create_task`."""
        return self._coro

    @property
    def status(self) -> TaskHandle.Status:
        """
        The current status of the task.

        Every task starts in the :attr:`~TaskHandle.Status.PENDING` state, and then
        transitions to one of the other states later. A pending task will transition
        from :attr:`~TaskHandle.Status.CANCELLING` to one of the final statuses, but no
        other status transitions will happen.

        """
        return self._status

    @property
    def name(self) -> str:
        """The name of the task."""
        return self._name

    @property
    def exception(self) -> BaseException | None:
        """
        The exception raised by the task, or ``None`` if it finished without raising.

        :raises RuntimeError: if the task has not returned yet
        :raises TaskCancelled: if the task was cancelled

        """
        match self._status:
            case TaskHandle.Status.PENDING:
                raise RuntimeError("the task has not returned yet")
            case TaskHandle.Status.FINISHED:
                return None
            case TaskHandle.Status.CANCELLING | TaskHandle.Status.CANCELLED:
                raise TaskCancelled("the task was cancelled")
            case TaskHandle.Status.ERRORED:
                return self._exception

    @property
    def return_value(self) -> T_co:
        """
        The return value of the task.

        :raises RuntimeError: if the task has not returned yet
        :raises TaskCancelled: if the task was cancelled
        :raises TaskError: if the task raised an exception

        """
        match self._status:
            case TaskHandle.Status.PENDING:
                raise RuntimeError("the task has not returned yet")
            case TaskHandle.Status.FINISHED:
                return self._return_value
            case TaskHandle.Status.CANCELLING | TaskHandle.Status.CANCELLED:
                raise TaskCancelled("the task was cancelled")
            case TaskHandle.Status.ERRORED:
                raise TaskError("the task raised an exception") from self._exception

    async def wait(self) -> None:
        """
        Wait for the task to finish.

        This method will return as soon as the task has finished, no matter how it
        happened.

        """
        await self._finished_event.wait()

    def __await__(self) -> Generator[Any, Any, T_co]:
        yield from self._finished_event.wait().__await__()
        return self.return_value

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} {self._status.name.lower()} "
            f"name={self._name!r} coro={self._coro!r}>"
        )
