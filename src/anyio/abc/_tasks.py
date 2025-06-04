from __future__ import annotations

import sys
from abc import ABCMeta, abstractmethod
from collections.abc import Awaitable, Callable
from contextlib import AbstractAsyncContextManager
from types import TracebackType
from typing import TYPE_CHECKING, Any, Protocol, TypeVar, overload

if sys.version_info >= (3, 11):
    from typing import TypeVarTuple, Unpack
else:
    from typing_extensions import TypeVarTuple, Unpack

if TYPE_CHECKING:
    from .._core._tasks import CancelScope

T_Retval = TypeVar("T_Retval")
T_contra = TypeVar("T_contra", contravariant=True)
PosArgsT = TypeVarTuple("PosArgsT")


class TaskStatus(Protocol[T_contra]):
    @overload
    def started(self: TaskStatus[None]) -> None: ...

    @overload
    def started(self, value: T_contra) -> None: ...

    def started(self, value: T_contra | None = None) -> None:
        """
        Signal that the task has started.

        :param value: object passed back to the starter of the task
        """


class TaskGroup(metaclass=ABCMeta):
    """
    Groups several asynchronous tasks together.

    :ivar cancel_scope: the cancel scope inherited by all child tasks
    :vartype cancel_scope: CancelScope

    .. note:: On asyncio, support for eager task factories is considered to be
        **experimental**. In particular, they don't follow the usual semantics of new
        tasks being scheduled on the next iteration of the event loop, and may thus
        cause unexpected behavior in code that wasn't written with such semantics in
        mind.
    """

    cancel_scope: CancelScope

    @abstractmethod
    def start_soon(
        self,
        func: Callable[[Unpack[PosArgsT]], Awaitable[Any]],
        *args: Unpack[PosArgsT],
        name: object = None,
    ) -> None:
        """
        Start a new task in this task group.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging

        .. versionadded:: 3.0
        """

    @abstractmethod
    async def start(
        self,
        func: Callable[..., Awaitable[Any]],
        *args: object,
        name: object = None,
    ) -> Any:
        """
        Start a new task and wait until it signals for readiness.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging
        :return: the value passed to ``task_status.started()``
        :raises RuntimeError: if the task finishes without calling
            ``task_status.started()``

        .. versionadded:: 3.0
        """

    async def start_context(
        self, ctx: AbstractAsyncContextManager[T_Retval], *, name: object = None
    ) -> T_Retval:
        """Start a new task by waiting until the context manager has been entered.

        The remainder of the task will run until the context manager's exit method has completed.

        :param ctx: an asynchronous context manager
        :param name: name of the task, for the purposes of introspection and debugging
        :return: The value yielded by the context manager's ``__aenter__`` method.

        .. versionadded:: X.Y
        """
        return await self.start(_start_context, ctx, name=name)

    @abstractmethod
    async def __aenter__(self) -> TaskGroup:
        """Enter the task group context and allow starting new tasks."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool:
        """Exit the task group context waiting for all tasks to finish."""


async def _start_context(
    ctx: AbstractAsyncContextManager[T_Retval],
    *,
    task_status: TaskStatus[T_Retval],
) -> None:
    """
    Start a new task and wait until it signals for readiness.

    :param ctx: an asynchronous context manager
    :return: the value passed to ``task_status.started()``
    :raises RuntimeError: if the task finishes without calling
        ``task_status.started()``
    """
    async with ctx as retval:
        task_status.started(retval)
