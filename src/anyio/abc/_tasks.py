import typing
from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Callable, Coroutine, Optional, Type, TypeVar

if typing.TYPE_CHECKING:
    from anyio._core._tasks import CancelScope

T_Retval = TypeVar('T_Retval')


class TaskStatus(metaclass=ABCMeta):
    @abstractmethod
    def started(self, value=None) -> None:
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

    cancel_scope: 'CancelScope'

    async def spawn(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        """
        Deprecated alios for :meth:`start_soon`.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging

        .. versionchanged:: 3.0
            Soft-deprecated; to be removed in v4.0.

        """
        self.start_soon(func, *args, name=name)

    @abstractmethod
    def start_soon(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        """
        Launch a new task in this task group.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging

        .. versionadded:: 3.0
        """

    @abstractmethod
    async def start(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        """
        Launch a new task and wait until it signals for readiness.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging
        :return: the value passed to ``task_status.started()``
        :raises RuntimeError: if the task finishes without calling ``task_status.started()``

        .. versionadded:: 3.0
        """

    @abstractmethod
    async def __aenter__(self) -> 'TaskGroup':
        """Enter the task group context and allow starting new tasks."""

    @abstractmethod
    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        """Exit the task group context waiting for all tasks to finish."""
