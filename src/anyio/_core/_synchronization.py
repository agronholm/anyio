from ..abc import CapacityLimiter, Condition, Event, Lock, Semaphore
from ._eventloop import get_asynclib
from ._exceptions import BusyResourceError


def create_lock() -> Lock:
    """
    Create an asynchronous lock.

    :return: a lock object

    """
    return get_asynclib().Lock()


def create_condition(lock: Lock = None) -> Condition:
    """
    Create an asynchronous condition.

    :param lock: the lock to base the condition object on
    :return: a condition object

    """
    return get_asynclib().Condition(lock=lock)


def create_event() -> Event:
    """
    Create an asynchronous event object.

    :return: an event object

    """
    return get_asynclib().Event()


def create_semaphore(value: int) -> Semaphore:
    """
    Create an asynchronous semaphore.

    :param value: the semaphore's initial value
    :return: a semaphore object

    """
    return get_asynclib().Semaphore(value)


def create_capacity_limiter(total_tokens: float) -> CapacityLimiter:
    """
    Create a capacity limiter.

    :param total_tokens: the total number of tokens available for borrowing (can be an integer or
        :data:`math.inf`)
    :return: a capacity limiter object

    """
    return get_asynclib().CapacityLimiter(total_tokens)


class ResourceGuard:
    __slots__ = 'action', '_guarded'

    def __init__(self, action: str):
        self.action = action
        self._guarded = False

    def __enter__(self):
        if self._guarded:
            raise BusyResourceError(self.action)

        self._guarded = True

    def __exit__(self, exc_type, exc_val, exc_tb):
        self._guarded = False
