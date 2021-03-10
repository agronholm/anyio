import math
from typing import Optional

from ..abc import CancelScope, TaskGroup, TaskStatus
from ._compat import DeprecatedAsyncContextManager, DeprecatedAwaitableFloat
from ._eventloop import get_asynclib


class _IgnoredTaskStatus(TaskStatus):
    def started(self, value=None) -> None:
        pass


TASK_STATUS_IGNORED = _IgnoredTaskStatus()


def open_cancel_scope(*, shield: bool = False) -> CancelScope:
    """
    Open a cancel scope.

    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a cancel scope

    """
    return get_asynclib().CancelScope(shield=shield)


class FailAfterContextManager(DeprecatedAsyncContextManager):
    def __init__(self, cancel_scope: CancelScope):
        self._cancel_scope = cancel_scope

    def __enter__(self):
        return self._cancel_scope.__enter__()

    def __exit__(self, exc_type, exc_val, exc_tb):
        retval = self._cancel_scope.__exit__(exc_type, exc_val, exc_tb)
        if self._cancel_scope.cancel_called:
            raise TimeoutError

        return retval


def fail_after(delay: Optional[float], shield: bool = False) -> FailAfterContextManager:
    """
    Create a context manager which raises a :class:`TimeoutError` if does not finish in time.

    :param delay: maximum allowed time (in seconds) before raising the exception, or ``None`` to
        disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a context manager that yields a cancel scope
    :rtype: :class:`~typing.ContextManager`\\[:class:`~anyio.abc.CancelScope`\\]

    """
    deadline = (get_asynclib().current_time() + delay) if delay is not None else math.inf
    cancel_scope = get_asynclib().CancelScope(deadline=deadline, shield=shield)
    return FailAfterContextManager(cancel_scope)


def move_on_after(delay: Optional[float], shield: bool = False) -> CancelScope:
    """
    Create a cancel scope with a deadline that expires after the given delay.

    :param delay: maximum allowed time (in seconds) before exiting the context block, or ``None``
        to disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a cancel scope

    """
    deadline = (get_asynclib().current_time() + delay) if delay is not None else math.inf
    return get_asynclib().CancelScope(deadline=deadline, shield=shield)


def current_effective_deadline() -> DeprecatedAwaitableFloat:
    """
    Return the nearest deadline among all the cancel scopes effective for the current task.

    :return: a clock value from the event loop's internal clock (``float('inf')`` if there is no
        deadline in effect)
    :rtype: float

    """
    return DeprecatedAwaitableFloat(get_asynclib().current_effective_deadline(),
                                    current_effective_deadline)


def create_task_group() -> TaskGroup:
    """
    Create a task group.

    :return: a task group

    """
    return get_asynclib().TaskGroup()
