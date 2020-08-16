from abc import abstractmethod
from ipaddress import IPv4Address, IPv6Address
from socket import AddressFamily, SocketType
from typing import (
    TypeVar, Tuple, Union, Generic, Callable, Any, Optional, AsyncContextManager)

from .tasks import TaskGroup
from .streams import UnreliableObjectStream, ByteStream, Listener, T_Stream

IPAddressType = Union[str, IPv4Address, IPv6Address]
IPSockAddrType = Tuple[str, int]
SockAddrType = Union[IPSockAddrType, str]
UDPPacketType = Tuple[bytes, IPSockAddrType]
T_Retval = TypeVar('T_Retval')
T_SockAddr = TypeVar('T_SockAddr', str, IPSockAddrType)


class _NullAsyncContextManager:
    async def __aenter__(self):
        pass

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


class SocketProvider(Generic[T_SockAddr]):
    """Abstract base class for socket-based streams and listeners."""

    @property
    @abstractmethod
    def raw_socket(self) -> SocketType:
        """
        The underlying raw socket object.

        .. warning:: This should only be used for advanced use cases, so only use this if you know
            what you're doing. Otherwise you might break things in subtle ways.
        """

    def getsockopt(self, level, optname, *args):
        """
        Get a socket option from the underlying socket.

        :return: the return value of :meth:`~socket.socket.getsockopt`

        """
        return self.raw_socket.getsockopt(level, optname, *args)

    def setsockopt(self, level, optname, value, *args) -> None:
        """
        Set a socket option on the underlying socket.

        This calls :meth:`~socket.socket.setsockopt` on the underlying socket.

        """
        self.raw_socket.setsockopt(level, optname, value, *args)

    @property
    def family(self) -> AddressFamily:
        """The address family of the underlying socket."""
        return self.raw_socket.family

    @property
    def local_address(self) -> T_SockAddr:
        """
        The bound address of the underlying local socket.

        For TCP streams, this is a tuple of (IP address, port).
        For UNIX socket streams, this is the path to the socket.

        """
        from anyio._core._sockets import convert_ipv6_sockaddr
        return convert_ipv6_sockaddr(self.raw_socket.getsockname())


class SocketStream(Generic[T_SockAddr], ByteStream, SocketProvider[T_SockAddr]):
    """Transports bytes over a socket."""

    @property
    def remote_address(self) -> T_SockAddr:
        """
        The address this socket is connected to.

        For TCP streams, this is a tuple of (IP address, port).
        For UNIX socket streams, this is the path to the socket.

        """
        from anyio._core._sockets import convert_ipv6_sockaddr
        return convert_ipv6_sockaddr(self.raw_socket.getpeername())


class SocketListener(Generic[T_SockAddr], Listener[SocketStream[T_SockAddr]],
                     SocketProvider[T_SockAddr]):
    """Listens to incoming socket connections."""

    @abstractmethod
    async def accept(self) -> SocketStream[T_SockAddr]:
        """Accept an incoming connection."""

    async def serve(self, handler: Callable[[T_Stream], Any],
                    task_group: Optional[TaskGroup] = None) -> None:
        from .. import create_task_group

        context_manager: AsyncContextManager
        if task_group is None:
            task_group = context_manager = create_task_group()
        else:
            # Can be replaced with AsyncExitStack once on py3.7+
            context_manager = _NullAsyncContextManager()

        # There is a mypy bug here
        async with context_manager:  # type: ignore[attr-defined]
            while True:
                stream = await self.accept()
                await task_group.spawn(handler, stream)


class UDPSocket(UnreliableObjectStream[UDPPacketType], SocketProvider[IPSockAddrType]):
    """Represents an unconnected UDP socket."""

    async def sendto(self, data: bytes, host: str, port: int) -> None:
        return await self.send((data, (host, port)))


class ConnectedUDPSocket(UnreliableObjectStream[bytes], SocketProvider[IPSockAddrType]):
    """Represents an connected UDP socket."""

    @property
    def remote_address(self) -> IPSockAddrType:
        """The address this socket is connected to."""
        from anyio._core._sockets import convert_ipv6_sockaddr
        return convert_ipv6_sockaddr(self.raw_socket.getpeername())
