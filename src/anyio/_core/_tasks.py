from typing import Any, AsyncContextManager, Coroutine, Optional

from ..abc import CancelScope, TaskGroup
from ._eventloop import get_asynclib


def open_cancel_scope(*, shield: bool = False) -> CancelScope:
    """
    Open a cancel scope.

    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: a cancel scope

    """
    return get_asynclib().CancelScope(shield=shield)


def fail_after(delay: Optional[float], *,
               shield: bool = False) -> AsyncContextManager[CancelScope]:
    """
    Create an async context manager which raises an exception if does not finish in time.

    :param delay: maximum allowed time (in seconds) before raising the exception, or ``None`` to
        disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope
    :rtype: :class:`~typing.AsyncContextManager`\\[:class:`~anyio.abc.CancelScope`\\]
    :raises TimeoutError: if the block does not complete within the allotted time

    """
    if delay is None:
        return get_asynclib().CancelScope(shield=shield)
    else:
        return get_asynclib().fail_after(delay, shield=shield)


def move_on_after(delay: Optional[float], *,
                  shield: bool = False) -> AsyncContextManager[CancelScope]:
    """
    Create an async context manager which is exited if it does not complete within the given time.

    :param delay: maximum allowed time (in seconds) before exiting the context block, or ``None``
        to disable the timeout
    :param shield: ``True`` to shield the cancel scope from external cancellation
    :return: an asynchronous context manager that yields a cancel scope
    :rtype: :class:`~typing.AsyncContextManager`\\[:class:`~anyio.abc.CancelScope`\\]

    """
    if delay is None:
        return get_asynclib().CancelScope(shield=shield)
    else:
        return get_asynclib().move_on_after(delay, shield=shield)


def current_effective_deadline() -> Coroutine[Any, Any, float]:
    """
    Return the nearest deadline among all the cancel scopes effective for the current task.

    :return: a clock value from the event loop's internal clock (``float('inf')`` if there is no
        deadline in effect)
    :rtype: float

    """
    return get_asynclib().current_effective_deadline()


def create_task_group() -> TaskGroup:
    """
    Create a task group.

    :return: a task group

    """
    return get_asynclib().TaskGroup()
