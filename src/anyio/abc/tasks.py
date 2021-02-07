from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Callable, Coroutine, Optional, Type, TypeVar

T_Retval = TypeVar('T_Retval')


class TaskGroup(metaclass=ABCMeta):
    """
    Groups several asynchronous tasks together.

    :ivar cancel_scope: the cancel scope inherited by all child tasks
    :vartype cancel_scope: CancelScope
    """

    cancel_scope: 'CancelScope'

    @abstractmethod
    async def spawn(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        """
        Launch a new task in this task group.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging
        """

    @abstractmethod
    async def __aenter__(self) -> 'TaskGroup':
        """Enter the task group context and allow starting new tasks."""

    @abstractmethod
    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        """Exit the task group context waiting for all tasks to finish."""


class CancelScope(metaclass=ABCMeta):
    @abstractmethod
    async def cancel(self) -> None:
        """Cancel this scope immediately."""

    @property
    @abstractmethod
    def deadline(self) -> float:
        """
        The time (clock value) when this scope is cancelled automatically.

        Will be ``float('inf')`` if no timeout has been set.
        """

    @property
    @abstractmethod
    def cancel_called(self) -> bool:
        """``True`` if :meth:`cancel` has been called."""

    @property
    @abstractmethod
    def shield(self) -> bool:
        """
        ``True`` if this scope is shielded from external cancellation.

        While a scope is shielded, it will not receive cancellations from outside.
        """

    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        pass
