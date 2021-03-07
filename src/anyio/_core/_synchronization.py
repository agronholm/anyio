from collections import deque
from dataclasses import dataclass
from types import TracebackType
from typing import Deque, Optional, Tuple, Type

from .. import abc
from ..lowlevel import checkpoint
from ._eventloop import get_asynclib
from ._exceptions import BusyResourceError, WouldBlock
from ._tasks import open_cancel_scope
from ._testing import TaskInfo, get_current_task


@dataclass(frozen=True)
class LockStatistics:
    """
    :ivar bool locked: flag indicating if this lock is locked or not
    :ivar ~anyio.TaskInfo owner: task currently holding the lock (or ``None`` if the lock is not
        held by any task)
    :ivar int tasks_waiting: number of tasks waiting on :meth:`~.Lock.acquire`
    """

    locked: bool
    owner: Optional[TaskInfo]
    tasks_waiting: int


@dataclass(frozen=True)
class ConditionStatistics:
    """
    :ivar int tasks_waiting: number of tasks blocked on :meth:`~.Condition.wait`
    :ivar ~anyio.LockStatistics lock_statistics: statistics of the underlying :class:`~.Lock`
    """

    tasks_waiting: int
    lock_statistics: LockStatistics


@dataclass(frozen=True)
class SemaphoreStatistics:
    """
    :ivar int tasks_waiting: number of tasks waiting on :meth:`~.Semaphore.acquire`

    """
    tasks_waiting: int


class Lock:
    _owner_task: Optional[TaskInfo] = None

    def __init__(self):
        self._waiters: Deque[Tuple[TaskInfo, abc.Event]] = deque()

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        self.release()

    async def acquire(self) -> None:
        """Acquire the lock."""
        await checkpoint()
        try:
            self.acquire_nowait()
        except WouldBlock:
            task = get_current_task()
            event = create_event()
            token = task, event
            self._waiters.append(token)
            try:
                await event.wait()
            except BaseException:
                if not event.is_set():
                    self._waiters.remove(token)

                raise

            assert self._owner_task == task

    def acquire_nowait(self) -> None:
        """
        Acquire the lock, without blocking.

        :raises ~WouldBlock: if the operation would block

        """
        task = get_current_task()
        if self._owner_task == task:
            raise RuntimeError('Attempted to acquire an already held Lock')

        if self._owner_task is not None:
            raise WouldBlock

        self._owner_task = task

    def release(self) -> None:
        """Release the lock."""
        if self._owner_task != get_current_task():
            raise RuntimeError('The current task is not holding this lock')

        if self._waiters:
            self._owner_task, event = self._waiters.popleft()
            event.set()
        else:
            del self._owner_task

    def locked(self) -> bool:
        """Return True if the lock is currently held."""
        return self._owner_task is not None

    def statistics(self) -> LockStatistics:
        """
        Return statistics about the current state of this lock.

        .. versionadded:: 3.0
        """
        return LockStatistics(self.locked(), self._owner_task, len(self._waiters))


class Condition:
    _owner_task: Optional[TaskInfo] = None

    def __init__(self, lock: Optional[Lock] = None):
        self._lock = lock or Lock()
        self._waiters: Deque[abc.Event] = deque()

    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        self.release()

    def _check_acquired(self) -> None:
        if self._owner_task != get_current_task():
            raise RuntimeError('The current task is not holding the underlying lock')

    async def acquire(self) -> None:
        """Acquire the underlying lock."""
        await self._lock.acquire()
        self._owner_task = get_current_task()

    def acquire_nowait(self) -> None:
        """
        Acquire the underlying lock, without blocking.

        :raises ~WouldBlock: if the operation would block

        """
        self._lock.acquire_nowait()
        self._owner_task = get_current_task()

    def release(self) -> None:
        """Release the underlying lock."""
        self._lock.release()

    def locked(self) -> bool:
        """Return True if the lock is set."""
        return self._lock.locked()

    def notify(self, n: int = 1) -> None:
        """Notify exactly n listeners."""
        self._check_acquired()
        for _ in range(n):
            try:
                event = self._waiters.popleft()
            except IndexError:
                break

            event.set()

    def notify_all(self) -> None:
        """Notify all the listeners."""
        self._check_acquired()
        for event in self._waiters:
            event.set()

        self._waiters.clear()

    async def wait(self) -> None:
        """Wait for a notification."""
        await checkpoint()
        event = create_event()
        self._waiters.append(event)
        self.release()
        try:
            await event.wait()
        except BaseException:
            if not event.is_set():
                self._waiters.remove(event)

            raise
        finally:
            with open_cancel_scope(shield=True):
                await self.acquire()

    def statistics(self) -> ConditionStatistics:
        """
        Return statistics about the current state of this condition.

        .. versionadded:: 3.0
        """
        return ConditionStatistics(len(self._waiters), self._lock.statistics())


class Semaphore:
    def __init__(self, initial_value: int, *, max_value: Optional[int]):
        if not isinstance(initial_value, int):
            raise TypeError('initial_value must be an integer')
        if initial_value < 0:
            raise ValueError('initial_value must be >= 0')
        if max_value is not None:
            if not isinstance(max_value, int):
                raise TypeError('max_value must be an integer or None')
            if max_value < initial_value:
                raise ValueError('max_value must be equal to or higher than initial_value')

        self._value = initial_value
        self._max_value = max_value
        self._waiters: Deque[abc.Event] = deque()

    async def __aenter__(self) -> 'Semaphore':
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        self.release()

    async def acquire(self) -> None:
        """Decrement the semaphore value, blocking if necessary."""
        try:
            self.acquire_nowait()
        except WouldBlock:
            event = create_event()
            self._waiters.append(event)
            try:
                await event.wait()
            except BaseException:
                if not event.is_set():
                    self._waiters.remove(event)

                raise

            self.acquire_nowait()

    def acquire_nowait(self) -> None:
        """
        Acquire the underlying lock, without blocking.

        :raises ~WouldBlock: if the operation would block

        """
        if self._value == 0:
            raise WouldBlock

        self._value -= 1

    def release(self) -> None:
        """Increment the semaphore value."""
        if self._max_value is not None and self._value == self._max_value:
            raise ValueError('semaphore released too many times')

        self._value += 1
        if self._waiters:
            self._waiters.popleft().set()

    @property
    def value(self) -> int:
        """The current value of the semaphore."""
        return self._value

    @property
    def max_value(self) -> Optional[int]:
        """The maximum value of the semaphore."""
        return self._max_value

    def statistics(self) -> SemaphoreStatistics:
        """
        Return statistics about the current state of this semaphore.

        .. versionadded:: 3.0
        """
        return SemaphoreStatistics(len(self._waiters))


def create_lock() -> Lock:
    """
    Create an asynchronous lock.

    :return: a lock object

    """
    return Lock()


def create_condition(lock: Optional[Lock] = None) -> Condition:
    """
    Create an asynchronous condition.

    :param lock: the lock to base the condition object on
    :return: a condition object

    """
    return Condition(lock=lock)


def create_event() -> abc.Event:
    """
    Create an asynchronous event object.

    :return: an event object

    """
    return get_asynclib().Event()


def create_semaphore(value: int, *, max_value: Optional[int] = None) -> Semaphore:
    """
    Create an asynchronous semaphore.

    :param value: the semaphore's initial value
    :param max_value: if set, makes this a "bounded" semaphore that raises :exc:`ValueError` if the
        semaphore's value would exceed this number
    :return: a semaphore object

    """
    return Semaphore(value, max_value=max_value)


def create_capacity_limiter(total_tokens: float) -> abc.CapacityLimiter:
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
