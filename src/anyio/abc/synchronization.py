from abc import ABCMeta, abstractmethod
from ipaddress import IPv4Address, IPv6Address
from types import TracebackType
from typing import Optional, Type, TypeVar, Union

T_Retval = TypeVar('T_Retval')
IPAddressType = Union[str, IPv4Address, IPv6Address]


class Event(metaclass=ABCMeta):
    @abstractmethod
    async def set(self) -> None:
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
        await self.release()

    @abstractmethod
    async def acquire(self) -> None:
        """Acquire the lock."""

    @abstractmethod
    async def release(self) -> None:
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
        await self.release()

    @abstractmethod
    async def acquire(self) -> None:
        """Acquire the underlying lock."""

    @abstractmethod
    async def release(self) -> None:
        """Release the underlying lock."""

    @abstractmethod
    def locked(self) -> bool:
        """Return True if the lock is set."""

    @abstractmethod
    async def notify(self, n: int = 1) -> None:
        """Notify exactly n listeners."""

    @abstractmethod
    async def notify_all(self) -> None:
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
        await self.release()

    @abstractmethod
    async def acquire(self) -> None:
        """Decrement the semaphore value, blocking if necessary."""

    @abstractmethod
    async def release(self) -> None:
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
        """The total number of tokens available for borrowing."""

    @abstractmethod
    async def set_total_tokens(self, value: float) -> None:
        """
        Set the total number of tokens.

        If the total number of tokens is increased, the proportionate number of tasks waiting on
        this limiter will be granted their tokens.

        :param value: the new total number of tokens (>= 1)
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
    async def acquire_nowait(self) -> None:
        """
        Acquire a token for the current task without waiting for one to become available.

        :raises ~anyio.WouldBlock: if there are no tokens available for borrowing
        """

    @abstractmethod
    async def acquire_on_behalf_of_nowait(self, borrower) -> None:
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
    async def release(self) -> None:
        """
        Release the token held by the current task.
        :raises RuntimeError: if the current task has not borrowed a token from this limiter.
        """

    @abstractmethod
    async def release_on_behalf_of(self, borrower) -> None:
        """
        Release the token held by the given borrower.

        :raises RuntimeError: if the borrower has not borrowed a token from this limiter.
        """
