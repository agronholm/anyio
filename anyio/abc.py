from abc import ABCMeta, abstractmethod
from io import SEEK_SET
from ipaddress import IPv4Address, IPv6Address
from ssl import SSLContext
from typing import Callable, TypeVar, Optional, Tuple, Union, AsyncIterable, Dict, List

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
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    @abstractmethod
    async def close(self) -> None:
        """Close the stream."""

    @property
    @abstractmethod
    def buffered_data(self) -> bytes:
        """Return the data currently in the read buffer."""

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
    def receive_chunks(self, max_size: int) -> AsyncIterable[bytes]:
        """
        Return an async iterable which yields chunks of bytes as soon as they are received.

        The generator will yield new chunks until the stream is closed.

        :param max_size: maximum number of bytes to return in one iteration
        :return: an async iterable yielding bytes
        """

    @abstractmethod
    def receive_delimited_chunks(self, delimiter: bytes,
                                 max_chunk_size: int) -> AsyncIterable[bytes]:
        """
        Return an async iterable which yields chunks of bytes as soon as they are received.

        The generator will yield new chunks until the stream is closed.

        :param delimiter: the marker to look for in the stream
        :param max_chunk_size: maximum number of bytes that will be read for each chunk before
            raising :exc:`~anyio.exceptions.DelimiterNotFound`
        :return: an async iterable yielding bytes
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
    @abstractmethod
    async def start_tls(self, context: Optional[SSLContext] = None) -> None:
        """
        Start the TLS handshake.

        If the handshake fails, the stream will be closed.

        :param context: an explicit SSL context to use for the handshake
        """

    @abstractmethod
    def getpeercert(self, binary_form: bool = False) -> Union[Dict[str, Union[str, tuple]],
                                                              bytes, None]:
        """
        Get the certificate for the peer on the other end of the connection.

        See :func:`ssl.SSLSocket.getpeercert` for more information.

        :param binary_form: ``False`` to return the certificate as a dict, ``True`` to return it
            as bytes
        :return: the peer's certificate, or ``None`` if there is not certificate for the peer
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def alpn_protocol(self) -> Optional[str]:
        """
        Return the ALPN protocol selected during the TLS handshake.

        :return: The selected ALPN protocol, or ``None`` if no ALPN protocol was selected
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @abstractmethod
    def get_channel_binding(self, cb_type: str = 'tls-unique') -> bytes:
        """
        Get the channel binding data for the current connection.

        See :func:`ssl.SSLSocket.get_channel_binding` for more information.

        :param cb_type: type of the channel binding to get
        :return: the channel binding data
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def tls_version(self) -> Optional[str]:
        """
        Return the TLS version negotiated during the TLS handshake.

        See :func:`ssl.SSLSocket.version` for more information.

        :return: the TLS version string (e.g. "TLSv1.3"), or ``None`` if the underlying socket is
            not using TLS
        """

    @property
    @abstractmethod
    def cipher(self) -> Tuple[str, str, int]:
        """
        Return the cipher selected in the TLS handshake.

        See :func:`ssl.SSLSocket.cipher` for more information.

        :return: a 3-tuple of (cipher name, TLS version which defined it, number of bits)
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def shared_ciphers(self) -> List[Tuple[str, str, int]]:
        """
        Return the list of ciphers supported by both parties in the TLS handshake.

        See :func:`ssl.SSLSocket.shared_ciphers` for more information.

        :return: a list of 3-tuples (cipher name, TLS version which defined it, number of bits)
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def server_hostname(self) -> Optional[str]:
        """
        Return the server host name.

        :return: the server host name, or ``None`` if this is the server side of the connection
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def server_side(self) -> bool:
        """
        Check if this is the server or client side of the connection.

        :return: ``True`` if this is the server side, ``False`` if this is the client side
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """


class SocketStreamServer(metaclass=ABCMeta):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    @abstractmethod
    async def close(self) -> None:
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

    @abstractmethod
    def accept_connections(self) -> AsyncIterable[SocketStream]:
        """
        Return an async iterable yielding streams from accepted incoming connections.

        :return: an async context manager
        """


class DatagramSocket(metaclass=ABCMeta):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    @abstractmethod
    async def close(self) -> None:
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
        """
        Receive a datagram.

        No more than ``max_bytes`` of the received datagram will be returned, even if the datagram
        was really larger.

        :param max_bytes: maximum amount of bytes to be returned
        :return: the bytes received
        """

    @abstractmethod
    def receive_packets(self, max_size: int) -> AsyncIterable[Tuple[bytes, str]]:
        """
        Return an async iterable which yields packets read from the socket.

        The iterable exits if the socket is closed.

        :return: an async iterable yielding (bytes, source address) tuples
        """

    @abstractmethod
    async def send(self, data: BufferType, address: Optional[str] = None,
                   port: Optional[int] = None) -> None:
        """
        Send a datagram.

        If the default destination has been set, then ``address`` and ``port`` are optional.

        :param data: the datagram to send
        :param address: the destination IP address or host name
        :param port: the destination port
        """
