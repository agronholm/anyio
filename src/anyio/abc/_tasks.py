import functools
import typing
from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Any, Callable, Coroutine, Optional, Type, TypeVar
from warnings import warn
import sys

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

if typing.TYPE_CHECKING:
    from anyio._core._tasks import CancelScope

T_Retval = TypeVar('T_Retval')
T_ParamSpec = ParamSpec("T_ParamSpec")

class TaskStatus(metaclass=ABCMeta):
    @abstractmethod
    def started(self, value: object = None) -> None:
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

    async def spawn(self, func: Callable[..., Coroutine[Any, Any, Any]],
                    *args: object, name: object = None) -> None:
        """
        Start a new task in this task group.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging

        .. deprecated:: 3.0
           Use :meth:`start_soon` instead. If your code needs AnyIO 2 compatibility, you
           can keep using this until AnyIO 4.

        """
        warn('spawn() is deprecated -- use start_soon() (without the "await") instead',
             DeprecationWarning)
        self.start_soon(func, *args, name=name)

    def soonify(self, func: Callable[T_ParamSpec, Coroutine[Any, Any, Any]],
                name: object = None) -> Callable[T_ParamSpec, None]:
        """
        Create and return a function that when called will start a new task in this
        task group.

        Internally it uses the same ``task_group.start_soon()`` method. But 
        ``task_group.soonify()`` supports keyword arguments additional to positional
        arguments and it adds better support for autocompletion and inline errors
        for the arguments of the function called.

        Use it like this:

            async def do_work(arg1, arg2, kwarg1="", kwarg2=""):
                # Do work

            task_group.soonify(some_async_func)("spam", "ham", kwarg1="a", kwarg2="b")

        :param func: a coroutine function
        :param name: name of the task, for the purposes of introspection and debugging
        :return: a function that takes positional and keyword arguments and when called
            uses task_group.start_soon() to start the task in this task group.

        .. versionadded:: 3.4.1
        """
        def wrapper(*args: T_ParamSpec.args, **kwargs: T_ParamSpec.kwargs) -> None:
            partial_f = functools.partial(func, *args, **kwargs)
            return self.start_soon(partial_f, name=name)
        return wrapper

    @abstractmethod
    def start_soon(self, func: Callable[..., Coroutine[Any, Any, Any]],
                   *args: object, name: object = None) -> None:
        """
        Start a new task in this task group.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging

        .. versionadded:: 3.0
        """

    @abstractmethod
    async def start(self, func: Callable[..., Coroutine[Any, Any, Any]],
                    *args: object, name: object = None) -> object:
        """
        Start a new task and wait until it signals for readiness.

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
