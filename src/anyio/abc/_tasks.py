from __future__ import annotations

from abc import ABCMeta, abstractmethod
from collections.abc import Awaitable, Callable, Coroutine
from types import TracebackType
from typing import TYPE_CHECKING, Any, Generic, TypeVar

if TYPE_CHECKING:
    from mypy_extensions import NamedArg, VarArg
    from trio_typing import takes_callable_and_args

    from .._core._tasks import CancelScope
else:

    def takes_callable_and_args(fn):
        return fn


T_Retval = TypeVar("T_Retval")


class TaskStatus(Generic[T_Retval]):
    @abstractmethod
    def started(self, value: T_Retval | None = None) -> None:
        """
        Signal that the task has started.

        :param value: object passed back to the starter of the task
        """


class TaskGroup(metaclass=ABCMeta):
    """
    Groups several asynchronous tasks together.

    :ivar cancel_scope: the cancel scope inherited by all child tasks
    :vartype cancel_scope: CancelScope
    """

    cancel_scope: CancelScope

    @abstractmethod
    @takes_callable_and_args
    def start_soon(
        self,
        func: Callable[..., Coroutine[Any, Any, Any]]
        | Callable[[VarArg()], Coroutine[Any, Any, Any]],
        *args: Any,
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
    @takes_callable_and_args
    async def start(
        self,
        func: Callable[..., Awaitable[Any]]
        | Callable[
            [VarArg(), NamedArg(TaskStatus[T_Retval], "task_status")],  # noqa: F821
            Awaitable[Any],
        ],
        *args: Any,
        name: object = None,
    ) -> T_Retval:
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

    @abstractmethod
    async def __aenter__(self) -> TaskGroup:
        """Enter the task group context and allow starting new tasks."""

    @abstractmethod
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        """Exit the task group context waiting for all tasks to finish."""
