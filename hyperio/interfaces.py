from abc import ABCMeta, abstractmethod
from ipaddress import IPv4Address, IPv6Address
from ssl import SSLContext
from typing import Callable, TypeVar, Optional, Tuple, Union, Iterable, Any, List

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


class Socket(metaclass=ABCMeta):
    @abstractmethod
    async def __aenter__(self) -> 'StreamingSocket':
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    async def accept(self) -> Tuple['Socket', Any]:
        pass

    @abstractmethod
    def bind(self, address: Union[tuple, str, bytes]) -> None:
        pass

    # def close(self) -> None:
    #     super().close()

    @abstractmethod
    async def connect(self, address: Union[tuple, str, bytes]) -> None:
        pass

    @abstractmethod
    async def connect_ex(self, address: Union[tuple, str, bytes]) -> int:
        pass

    @abstractmethod
    def detach(self) -> int:
        pass

    @abstractmethod
    def fileno(self) -> int:
        pass

    @abstractmethod
    def getpeername(self) -> Any:
        pass

    @abstractmethod
    def getsockname(self) -> Any:
        pass

    @abstractmethod
    def getsockopt(self, level: int, optname: int, buflen: Optional[int] = None) -> bytes:
        pass

    @abstractmethod
    def ioctl(self, control: object, option: Tuple[int, int, int]) -> None:
        pass

    @abstractmethod
    def listen(self, backlog: int) -> None:
        pass

    @abstractmethod
    async def recv(self, bufsize: int, *, flags: int = 0) -> bytes:
        pass

    @abstractmethod
    async def recvfrom(self, bufsize: int, *, flags: int = 0) -> Any:
        pass

    @abstractmethod
    async def recvfrom_into(self, buffer, nbytes: int, *, flags: int = 0) -> Any:
        pass

    @abstractmethod
    async def recv_into(self, buffer, nbytes: int, *, flags: int = 0) -> Any:
        pass

    @abstractmethod
    async def send(self, data: bytes, *, flags: int = 0) -> int:
        pass

    @abstractmethod
    async def sendall(self, data: bytes, *, flags: int = 0) -> None:
        pass

    @abstractmethod
    async def sendto(self, data: bytes, address: Union[tuple, str], *, flags: int = 0) -> int:
        pass

    @abstractmethod
    def setsockopt(self, level: int, optname: int, value: Union[int, bytes]) -> None:
        pass

    @abstractmethod
    def shutdown(self, how: int) -> None:
        pass

    @abstractmethod
    def recvmsg(self, bufsize: int, ancbufsize: int = 0, *,
                flags: int = 0) -> Tuple[bytes, List, int, Any]:
        pass

    @abstractmethod
    def recvmsg_into(self, buffers: Iterable, ancbufsize: int = 0, *,
                     flags: int = 0) -> Tuple[int, List, int, Any]:
        pass

    @abstractmethod
    def sendmsg(self, buffers: Iterable[bytes], ancdata: Iterable = None, *,
                flags: int = 0, address: Any = None) -> int:
        pass


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
