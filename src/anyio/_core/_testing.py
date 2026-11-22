from __future__ import annotations

from collections import defaultdict
from collections.abc import AsyncGenerator, Awaitable, Generator
from contextlib import asynccontextmanager
from typing import Any, cast

from ._eventloop import get_async_backend, get_cancelled_exc_class


class Sequencer:
    """
    Run blocks of code in different tasks in an explicit order.

    Calling a sequencer with a sequence number returns an asynchronous context manager.
    Sequence numbers must be consecutive integers starting at zero. Block zero starts
    immediately, and each subsequent block waits for the preceding block to exit, even
    if that block raises an exception.

    Each sequence number can only be used once. Cancelling a task that is waiting for
    its turn breaks the sequence and causes current and future waiters to raise
    :exc:`RuntimeError`.
    """

    def __init__(self) -> None:
        from ._synchronization import Event

        self._sequence_points: defaultdict[int, Event] = defaultdict(Event)
        self._claimed: set[int] = set()
        self._broken = False

    # Based on trio.testing.Sequencer (see LICENSE.TRIO) and Thomas Grainger's
    # proposal in PR #262.
    @asynccontextmanager
    async def __call__(self, position: int) -> AsyncGenerator[None, None]:
        """
        Wait for the preceding block to exit and release the next block on exit.

        :param position: the block's sequence number, starting at zero
        :return: an asynchronous context manager for the block
        :rtype: ~contextlib.AbstractAsyncContextManager[None]
        :raises RuntimeError: if the sequence number has already been used or a waiter
            has been cancelled
        """
        if position in self._claimed:
            raise RuntimeError(f"Attempted to reuse sequence point {position}")
        elif self._broken:
            raise RuntimeError("sequence broken!")

        self._claimed.add(position)
        if position != 0:
            try:
                await self._sequence_points[position].wait()
            except get_cancelled_exc_class():
                self._broken = True
                for event in self._sequence_points.values():
                    event.set()

                raise RuntimeError(
                    "Sequencer wait cancelled -- sequence broken"
                ) from None
            else:
                if self._broken:
                    raise RuntimeError("sequence broken!")

        try:
            yield
        finally:
            self._sequence_points[position + 1].set()


class TaskInfo:
    """
    Represents an asynchronous task.

    :ivar int id: the unique identifier of the task
    :ivar parent_id: the identifier of the parent task, if any
    :vartype parent_id: Optional[int]
    :ivar str name: the description of the task (if any)
    :ivar ~collections.abc.Coroutine coro: the coroutine object of the task
    """

    __slots__ = "_name", "coro", "id", "name", "parent_id"

    def __init__(
        self,
        id: int,
        parent_id: int | None,
        name: str | None,
        coro: Generator[Any, Any, Any] | Awaitable[Any],
    ):
        func = get_current_task
        self._name = f"{func.__module__}.{func.__qualname__}"
        self.id: int = id
        self.parent_id: int | None = parent_id
        self.name: str | None = name
        self.coro: Generator[Any, Any, Any] | Awaitable[Any] = coro

    def __eq__(self, other: object) -> bool:
        if isinstance(other, TaskInfo):
            return self.id == other.id

        return NotImplemented

    def __hash__(self) -> int:
        return hash(self.id)

    def __repr__(self) -> str:
        return f"{self.__class__.__name__}(id={self.id!r}, name={self.name!r})"

    def has_pending_cancellation(self) -> bool:
        """
        Return ``True`` if the task has a cancellation pending, ``False`` otherwise.

        """
        return False


def get_current_task() -> TaskInfo:
    """
    Return the current task.

    :return: a representation of the current task
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread

    """
    return get_async_backend().get_current_task()


def get_running_tasks() -> list[TaskInfo]:
    """
    Return a list of running tasks in the current event loop.

    :return: a list of task info objects
    :raises NoEventLoopError: if no supported asynchronous event loop is running in the
        current thread

    """
    return cast("list[TaskInfo]", get_async_backend().get_running_tasks())


async def wait_all_tasks_blocked() -> None:
    """Wait until all other tasks are waiting for something."""
    await get_async_backend().wait_all_tasks_blocked()
