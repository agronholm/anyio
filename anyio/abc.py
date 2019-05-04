from abc import ABCMeta, abstractmethod
from io import SEEK_SET
from ipaddress import IPv4Address, IPv6Address
from ssl import SSLContext
from typing import Callable, TypeVar, Optional, Tuple, Union, AsyncIterable, Dict, List, Coroutine

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
        """Set the flag, notifying all listeners."""

    @abstractmethod
    def clear(self) -> None:
        """Clear the flag, so that listeners can receive another notification."""

    @abstractmethod
    def is_set(self) -> None:
        """Return ``True`` if the flag is set, ``False`` if not."""

    @abstractmethod
    async def wait(self) -> bool:
        """
        Wait until the flag has been set.

        If the flag has already been set when this method is called, it returns immediately.
        """


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
        """The current value of the semaphore."""


class Queue(metaclass=ABCMeta):
    @abstractmethod
    def empty(self) -> bool:
        """Return ``True`` if the queue is not holding any items."""

    @abstractmethod
    def full(self) -> bool:
        """Return ``True`` if the queue is holding the maximum number of items."""

    @abstractmethod
    def qsize(self) -> int:
        """Return the number of items the queue is currently holding."""

    @abstractmethod
    async def put(self, item) -> None:
        """
        Put an item into the queue.

        If the queue is currently full, this method will block until there is at least one free
        slot available.

        :param item: the object to put into the queue
        """

    @abstractmethod
    async def get(self):
        """
        Get an item from the queue.

        If there are no items in the queue, this method will block until one is available.

        :return: the removed item
        """


class TaskGroup(metaclass=ABCMeta):
    """
    Groups several asynchronous tasks together.

    :ivar cancel_scope: the cancel scope inherited by all child tasks
    :vartype cancel_scope: CancelScope
    """

    cancel_scope = None  # type: CancelScope

    @abstractmethod
    async def spawn(self, func: Callable[..., Coroutine], *args, name=None) -> None:
        """
        Launch a new task in this task group.

        :param func: a coroutine function
        :param args: positional arguments to call the function with
        :param name: name of the task, for the purposes of introspection and debugging
        """


class CancelScope(metaclass=ABCMeta):
    @abstractmethod
    async def cancel(self):
        """Cancel this scope immediately."""

    @property
    @abstractmethod
    def deadline(self) -> float:
        """
        The time (clock value) when this scope is cancelled automatically.

        Will be ``float('inf')``` if no timeout has been set.
        """

    @property
    @abstractmethod
    def cancel_called(self) -> bool:
        """``True`` if :meth:`cancel` has been called."""

    @property
    @abstractmethod
    def shield(self) -> bool:
        """
        ``True`` if this scope is shielded from external cancellation.

        While a scope is shielded, it will not receive cancellations from outside.
        """

    @abstractmethod
    async def __aenter__(self):
        pass

    @abstractmethod
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


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
    async def receive_some(self, max_bytes: int) -> bytes:
        """
        Reads up to the given amount of bytes from the stream.

        :param max_bytes: maximum number of bytes to read
        :return: the bytes read
        :raises ssl.SSLEOFError: if ``tls_standard_compatible`` was set to ``True`` in a TLS stream
            and the peer prematurely closed the connection
        """

    @abstractmethod
    async def receive_exactly(self, nbytes: int) -> bytes:
        """
        Read exactly the given amount of bytes from the stream.

        :param nbytes: the number of bytes to read
        :return: the bytes read
        :raises anyio.exceptions.IncompleteRead: if the stream was closed before the requested
            amount of bytes could be read from the stream
        :raises ssl.SSLEOFError: if ``tls_standard_compatible`` was set to ``True`` in a TLS stream
            and the peer prematurely closed the connection
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
        :raises ssl.SSLEOFError: if ``tls_standard_compatible`` was set to ``True`` in a TLS stream
            and the peer prematurely closed the connection
        """

    @abstractmethod
    def receive_chunks(self, max_size: int) -> AsyncIterable[bytes]:
        """
        Return an async iterable which yields chunks of bytes as soon as they are received.

        The generator will yield new chunks until the stream is closed.

        :param max_size: maximum number of bytes to return in one iteration
        :return: an async iterable yielding bytes
        :raises ssl.SSLEOFError: if ``tls_standard_compatible`` was set to ``True`` in a TLS stream
            and the peer prematurely closed the connection
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
        :raises ssl.SSLEOFError: if ``tls_standard_compatible`` was set to ``True`` in a TLS stream
            and the peer prematurely closed the connection
        """

    @abstractmethod
    async def send_all(self, data: bytes) -> None:
        """
        Send all of the given data to the other end.

        :param data: the bytes to send
        """


class SocketStream(Stream):
    @abstractmethod
    def getsockopt(self, level, optname, *args):
        """
        Get a socket option from the underlying socket.

        :return: the return value of :meth:`~socket.socket.getsockopt`
        """

    @abstractmethod
    def setsockopt(self, level, optname, value, *args) -> None:
        """
        Set a socket option.

        This calls :meth:`~socket.socket.setsockopt` on the underlying socket.
        """

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
        The ALPN protocol selected during the TLS handshake.

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
        The TLS version negotiated during the TLS handshake.

        See :func:`ssl.SSLSocket.version` for more information.

        :return: the TLS version string (e.g. "TLSv1.3"), or ``None`` if the underlying socket is
            not using TLS
        """

    @property
    @abstractmethod
    def cipher(self) -> Tuple[str, str, int]:
        """
        The cipher selected in the TLS handshake.

        See :func:`ssl.SSLSocket.cipher` for more information.

        :return: a 3-tuple of (cipher name, TLS version which defined it, number of bits)
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def shared_ciphers(self) -> List[Tuple[str, str, int]]:
        """
        The list of ciphers supported by both parties in the TLS handshake.

        See :func:`ssl.SSLSocket.shared_ciphers` for more information.

        :return: a list of 3-tuples (cipher name, TLS version which defined it, number of bits)
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def server_hostname(self) -> Optional[str]:
        """
        The server host name.

        :return: the server host name, or ``None`` if this is the server side of the connection
        :raises anyio.exceptions.TLSRequired: if a TLS handshake has not been done
        """

    @property
    @abstractmethod
    def server_side(self) -> bool:
        """
        ``True`` if this is the server side of the connection, ``False`` if this is the client.

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

    @abstractmethod
    def getsockopt(self, level, optname, *args):
        """
        Get a socket option from the underlying socket.

        :return: the return value of :meth:`~socket.socket.getsockopt`
        """

    @abstractmethod
    def setsockopt(self, level, optname, value, *args) -> None:
        """
        Set a socket option.

        This calls :meth:`~socket.socket.setsockopt` on the underlying socket.
        """

    @property
    @abstractmethod
    def address(self) -> Union[Tuple[str, int], Tuple[str, int, int, int], str]:
        """Return the bound address of the underlying socket."""

    @property
    @abstractmethod
    def port(self) -> int:
        """
        The currently bound port of the underlying TCP socket.

        Equivalent to ``server.address[1]``.
        :raises ValueError: if the socket is not a TCP socket
        """

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


class UDPSocket(metaclass=ABCMeta):
    async def __aenter__(self):
        return self

    async def __aexit__(self, *exc_info):
        await self.close()

    @abstractmethod
    async def close(self) -> None:
        """Close the underlying socket."""

    @property
    @abstractmethod
    def address(self) -> Union[Tuple[str, int], Tuple[str, int, int, int]]:
        """Return the bound address of the underlying socket."""

    @property
    @abstractmethod
    def port(self) -> int:
        """
        Return the currently bound port of the underlying socket.

        Equivalent to ``socket.address[1]``.
        """

    @abstractmethod
    def getsockopt(self, level, optname, *args):
        """
        Get a socket option from the underlying socket.

        :return: the return value of :meth:`~socket.socket.getsockopt`
        """

    @abstractmethod
    def setsockopt(self, level, optname, value, *args) -> None:
        """
        Set a socket option.

        This calls :meth:`~socket.socket.setsockopt` on the underlying socket.
        """

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
    async def send(self, data: bytes, address: Optional[str] = None,
                   port: Optional[int] = None) -> None:
        """
        Send a datagram.

        If the default destination has been set, then ``address`` and ``port`` are optional.

        :param data: the bytes to send
        :param address: the destination IP address or host name
        :param port: the destination port
        """
