from abc import ABCMeta, abstractmethod
from ipaddress import IPv4Address, IPv6Address
from ssl import SSLContext
from typing import Callable, TypeVar, Optional, Tuple, Union

T_Retval = TypeVar('T_Retval')
IPAddressType = Union[str, IPv4Address, IPv6Address]


class Lock(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    def locked(self) -> bool:
        """Return True if the lock is currently held."""


class Condition(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

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


class Event(metaclass=ABCMeta):
    @abstractmethod
    async def set(self) -> None:
        pass

    @abstractmethod
    def clear(self) -> None:
        pass

    @abstractmethod
    def is_set(self) -> None:
        pass

    @abstractmethod
    async def wait(self) -> bool:
        pass


class Semaphore(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @property
    @abstractmethod
    def value(self) -> int:
        pass


class Queue(metaclass=ABCMeta):
    @abstractmethod
    def empty(self) -> bool:
        pass

    @abstractmethod
    def full(self) -> bool:
        pass

    @abstractmethod
    def qsize(self) -> int:
        pass

    @abstractmethod
    async def put(self, item) -> None:
        pass

    @abstractmethod
    async def get(self):
        pass


class TaskGroup(metaclass=ABCMeta):
    cancel_scope = None  # type: CancelScope

    @abstractmethod
    async def spawn(self, func: Callable, *args, name=None) -> None:
        pass


class CancelScope(metaclass=ABCMeta):
    @abstractmethod
    async def cancel(self):
        """Cancel all tasks within this scope."""


class StreamingSocket(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self) -> 'StreamingSocket':
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    async def read(self, nbytes: Optional[int] = None) -> bytes:
        pass

    @abstractmethod
    async def read_exactly(self, nbytes: int) -> bytes:
        pass

    @abstractmethod
    async def read_until(self, delimiter: bytes, max_bytes: int) -> bytes:
        pass

    @abstractmethod
    async def send(self, data: bytes) -> None:
        pass

    @abstractmethod
    async def start_tls(self, ssl_context: Optional[SSLContext] = None) -> None:
        pass


class DatagramSocket(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self) -> 'DatagramSocket':
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    async def read(self) -> Tuple[bytes, str]:
        pass

    @abstractmethod
    async def send(self, data: bytes, address: str) -> None:
        pass
