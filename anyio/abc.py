from abc import ABCMeta, abstractmethod
from io import SEEK_SET
from ipaddress import IPv4Address, IPv6Address
from ssl import SSLContext
from typing import Callable, TypeVar, Optional, Tuple, Union

T_Retval = TypeVar('T_Retval')
IPAddressType = Union[str, IPv4Address, IPv6Address]
BufferType = Union[bytes, bytearray, memoryview]


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


class AsyncFile(metaclass=ABCMeta):
    """
    An asynchronous file object.

    This class wraps a standard file object and provides async friendly versions of the following
    blocking methods (where available on the original file object):

    * read
    * read1
    * readline
    * readlines
    * readinto
    * readinto1
    * write
    * writelines
    * truncate
    * seek
    * tell
    * flush
    * close

    All other methods are directly passed through.

    This class supports the asynchronous context manager protocol which closes the underlying file
    at the end of the context block.

    This class also supports asynchronous iteration::

        async with await aopen(...) as f:
            async for line in f:
                print(line)
    """

    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass

    @abstractmethod
    async def __aiter__(self):
        pass

    @abstractmethod
    async def read(self, size: int = -1) -> Union[bytes, str]:
        pass

    @abstractmethod
    async def read1(self, size: int = -1) -> Union[bytes, str]:
        pass

    @abstractmethod
    async def readline(self) -> bytes:
        pass

    @abstractmethod
    async def readlines(self) -> bytes:
        pass

    @abstractmethod
    async def readinto(self, b: Union[bytes, memoryview]) -> bytes:
        pass

    @abstractmethod
    async def readinto1(self, b: Union[bytes, memoryview]) -> bytes:
        pass

    @abstractmethod
    async def write(self, b: bytes) -> None:
        pass

    @abstractmethod
    async def writelines(self, lines: bytes) -> None:
        pass

    @abstractmethod
    async def truncate(self, size: Optional[int] = None) -> int:
        pass

    @abstractmethod
    async def seek(self, offset: int, whence: Optional[int] = SEEK_SET) -> int:
        pass

    @abstractmethod
    async def tell(self) -> int:
        pass

    @abstractmethod
    async def flush(self) -> None:
        pass

    @abstractmethod
    async def close(self) -> None:
        pass


class Stream(metaclass=ABCMeta):
    @abstractmethod
    async def receive_some(self, max_bytes: Optional[int]) -> bytes:
        """
        Reads up to the given amount of bytes from the stream.

        :param max_bytes: maximum number of bytes to read
        :return: the bytes read
        """

    @abstractmethod
    async def receive_exactly(self, nbytes: int) -> bytes:
        """
        Read exactly the given amount of bytes from the stream.

        :param nbytes: the number of bytes to read
        :return: the bytes read
        :raises anyio.exceptions.IncompleteRead: if the stream was closed before the requested
            amount of bytes could be read from the stream
        """

    @abstractmethod
    async def receive_until(self, delimiter: bytes, max_bytes: int) -> bytes:
        """
        Read from the stream until the delimiter is found or max_bytes have been read.

        :param delimiter: the marker to look for in the stream
        :param max_bytes: maximum number of bytes that will be read before raising
            :exc:`~anyio.exceptions.DelimiterNotFound`
        :return: the bytes read, including the delimiter
        :raises anyio.exceptions.IncompleteRead: if the stream was closed before the delimiter
            was found
        :raises anyio.exceptions.DelimiterNotFound: if the delimiter is not found within the
            bytes read up to the maximum allowed
        """

    @abstractmethod
    async def send_all(self, data: BufferType) -> None:
        """
        Send all of the given data to the other end.

        :param data: the buffer to send
        """


class SocketStream(Stream):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.close()

    @abstractmethod
    def close(self) -> None:
        """Close the underlying socket."""

    @abstractmethod
    async def start_tls(self, context: Optional[SSLContext] = None) -> None:
        pass


class SocketStreamServer(metaclass=ABCMeta):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.close()

    @abstractmethod
    def close(self) -> None:
        """Close the underlying socket."""

    @property
    @abstractmethod
    def address(self) -> Union[Tuple[str, int], str]:
        """Return the bound address of the underlying socket."""

    @property
    def port(self) -> int:
        """
        Return the currently bound port of the underlying socket.

        Equivalent to ``server.address[1]``.
        """
        return self.address[1]

    @abstractmethod
    async def accept(self) -> SocketStream:
        """
        Accept an incoming connection.

        :return: the socket stream for the accepted connection
        """


class DatagramSocket(metaclass=ABCMeta):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        self.close()

    @abstractmethod
    def close(self) -> None:
        """Close the underlying socket."""

    @property
    @abstractmethod
    def address(self) -> Tuple[str, int]:
        """Return the bound address of the underlying socket."""

    @property
    def port(self) -> int:
        """
        Return the currently bound port of the underlying socket.

        Equivalent to ``socket.address[1]``.
        """
        return self.address[1]

    @abstractmethod
    async def receive(self, max_bytes: int) -> Tuple[bytes, str]:
        pass

    @abstractmethod
    async def send(self, data: BufferType, address: Optional[str] = None,
                   port: Optional[int] = None) -> None:
        pass
