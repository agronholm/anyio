from abc import ABCMeta, abstractmethod
from ipaddress import IPv4Address, IPv6Address
from ssl import SSLContext
from types import TracebackType
from typing import TypeVar, Optional, Tuple, Union, AsyncIterable, Dict, List, Type

from .streams import ByteStream

T_Retval = TypeVar('T_Retval')
IPAddressType = Union[str, IPv4Address, IPv6Address]


class SocketStream(ByteStream):
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
    def address(self) -> Union[Tuple[str, int], Tuple[str, int, int, int], str]:
        """
        Return the bound address of the underlying local socket.

        For IPv4 TCP streams, this is a tuple of (IP address, port).
        For IPv6 TCP streams, this is a tuple of (IP address, port, flowinfo, scopeid).
        For UNIX socket streams, this is the path to the socket.

        """
        raise NotImplementedError

    @property
    def peer_address(self) -> Union[Tuple[str, int], Tuple[str, int, int, int], str]:
        """
        Return the address this socket is connected to.

        For IPv4 TCP streams, this is a tuple of (IP address, port).
        For IPv6 TCP streams, this is a tuple of (IP address, port, flowinfo, scopeid).
        For UNIX socket streams, this is the path to the socket.

        """
        raise NotImplementedError

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

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        await self.aclose()

    @abstractmethod
    async def aclose(self) -> None:
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

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> None:
        await self.aclose()

    @abstractmethod
    async def aclose(self) -> None:
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
    async def receive(self, max_bytes: int) -> Tuple[bytes, Tuple[str, int]]:
        """
        Receive a datagram.

        No more than ``max_bytes`` of the received datagram will be returned, even if the datagram
        was really larger.

        :param max_bytes: maximum amount of bytes to be returned
        :return: a tuple of (bytes received, (source IP address, source port))
        """

    @abstractmethod
    def receive_packets(self, max_size: int) -> AsyncIterable[Tuple[bytes, str]]:
        """
        Return an async iterable which yields packets read from the socket.

        The iterable exits if the socket is closed.

        :return: an async iterable yielding (bytes, source address) tuples
        """

    @abstractmethod
    async def send(self, data: bytes, address: Optional[IPAddressType] = None,
                   port: Optional[int] = None) -> None:
        """
        Send a datagram.

        If the default destination has been set, then ``address`` and ``port`` are optional.

        :param data: the bytes to send
        :param address: the destination IP address or host name
        :param port: the destination port
        """
