from abc import ABCMeta, abstractmethod
from types import TracebackType
from typing import Optional, Type, TypeVar

T_Retval = TypeVar('T_Retval')


class Event(metaclass=ABCMeta):
    @abstractmethod
    def set(self) -> None:
        """Set the flag, notifying all listeners."""

    @abstractmethod
    def is_set(self) -> bool:
        """Return ``True`` if the flag is set, ``False`` if not."""

    @abstractmethod
    async def wait(self) -> bool:
        """
        Wait until the flag has been set.

        If the flag has already been set when this method is called, it returns immediately.
        """


class Lock(metaclass=ABCMeta):
    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        self.release()

    @abstractmethod
    async def acquire(self) -> None:
        """Acquire the lock."""

    @abstractmethod
    def release(self) -> None:
        """Release the lock."""

    @abstractmethod
    def locked(self) -> bool:
        """Return True if the lock is currently held."""


class Condition(metaclass=ABCMeta):
    async def __aenter__(self):
        await self.acquire()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        self.release()

    @abstractmethod
    async def acquire(self) -> None:
        """Acquire the underlying lock."""

    @abstractmethod
    def release(self) -> None:
        """Release the underlying lock."""

    @abstractmethod
    def locked(self) -> bool:
        """Return True if the lock is set."""

    @abstractmethod
    def notify(self, n: int = 1) -> None:
        """Notify exactly n listeners."""

    @abstractmethod
    def notify_all(self) -> None:
        """Notify all the listeners."""

    @abstractmethod
    async def wait(self) -> None:
        """Wait for a notification."""


class Semaphore(metaclass=ABCMeta):
    async def __aenter__(self) -> 'Semaphore':
        await self.acquire()
        return self

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        self.release()

    @abstractmethod
    async def acquire(self) -> None:
        """Decrement the semaphore value, blocking if necessary."""

    @abstractmethod
    def release(self) -> None:
        """Increment the semaphore value."""

    @property
    @abstractmethod
    def value(self) -> int:
        """The current value of the semaphore."""


class CapacityLimiter(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        pass

    @property
    @abstractmethod
    def total_tokens(self) -> float:
        """
        The total number of tokens available for borrowing.

        This is a read-write property. If the total number of tokens is increased, the
        proportionate number of tasks waiting on this limiter will be granted their tokens.

        .. versionchanged:: 3.0
            The property is now writable.
        """

    @property
    @abstractmethod
    def borrowed_tokens(self) -> int:
        """The number of tokens that have currently been borrowed."""

    @property
    @abstractmethod
    def available_tokens(self) -> float:
        """The number of tokens currently available to be borrowed"""

    @abstractmethod
    def acquire_nowait(self) -> None:
        """
        Acquire a token for the current task without waiting for one to become available.

        :raises ~anyio.WouldBlock: if there are no tokens available for borrowing
        """

    @abstractmethod
    def acquire_on_behalf_of_nowait(self, borrower) -> None:
        """
        Acquire a token without waiting for one to become available.

        :param borrower: the entity borrowing a token
        :raises ~anyio.WouldBlock: if there are no tokens available for borrowing
        """

    @abstractmethod
    async def acquire(self) -> None:
        """
        Acquire a token for the current task, waiting if necessary for one to become available.
        """

    @abstractmethod
    async def acquire_on_behalf_of(self, borrower) -> None:
        """
        Acquire a token, waiting if necessary for one to become available.

        :param borrower: the entity borrowing a token
        """

    @abstractmethod
    def release(self) -> None:
        """
        Release the token held by the current task.
        :raises RuntimeError: if the current task has not borrowed a token from this limiter.
        """

    @abstractmethod
    def release_on_behalf_of(self, borrower) -> None:
        """
        Release the token held by the given borrower.

        :raises RuntimeError: if the borrower has not borrowed a token from this limiter.
        """
