from abc import abstractmethod
from ipaddress import IPv4Address, IPv6Address
from socket import AddressFamily, SocketType
from typing import Any, AsyncContextManager, Callable, Generic, Optional, Tuple, TypeVar, Union

from .._core._typedattr import TypedAttributeProvider, TypedAttributeSet, typed_attribute
from .streams import ByteStream, Listener, T_Stream, UnreliableObjectStream
from .tasks import TaskGroup

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


class SocketAttribute(TypedAttributeSet):
    #: the address family of the underlying socket
    family: AddressFamily = typed_attribute()
    #: the local socket address of the underlying socket
    local_address: SockAddrType = typed_attribute()
    #: for IP addresses, the local port the underlying socket is bound to
    local_port: int = typed_attribute()
    #: the underlying stdlib socket object
    raw_socket: SocketType = typed_attribute()
    #: the remote address the underlying socket is connected to
    remote_address: SockAddrType = typed_attribute()
    #: for IP addresses, the remote port the underlying socket is connected to
    remote_port: int = typed_attribute()


class _SocketProvider(Generic[T_SockAddr], TypedAttributeProvider):
    @property
    def extra_attributes(self):
        from .._core._sockets import convert_ipv6_sockaddr as convert

        attributes = {
            SocketAttribute.family: lambda: self._raw_socket.family,
            SocketAttribute.local_address: lambda: convert(self._raw_socket.getsockname()),
            SocketAttribute.raw_socket: lambda: self._raw_socket
        }
        try:
            peername = convert(self._raw_socket.getpeername())
        except OSError:
            peername = None

        # Provide the remote address for connected sockets
        if peername is not None:
            attributes[SocketAttribute.remote_address] = lambda: peername

        # Provide local and remote ports for IP based sockets
        if self._raw_socket.family in (AddressFamily.AF_INET, AddressFamily.AF_INET6):
            attributes[SocketAttribute.local_port] = lambda: self._raw_socket.getsockname()[1]
            if peername is not None:
                attributes[SocketAttribute.remote_port] = lambda: peername[1]

        return attributes

    @property
    @abstractmethod
    def _raw_socket(self) -> SocketType:
        pass


class SocketStream(Generic[T_SockAddr], ByteStream, _SocketProvider[T_SockAddr]):
    """
    Transports bytes over a socket.

    Supports all relevant extra attributes from :class:`~SocketAttribute`.
    """


class SocketListener(Generic[T_SockAddr], Listener[SocketStream[T_SockAddr]],
                     _SocketProvider[T_SockAddr]):
    """
    Listens to incoming socket connections.

    Supports all relevant extra attributes from :class:`~SocketAttribute`.
    """

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

        async with context_manager:
            while True:
                stream = await self.accept()
                await task_group.spawn(handler, stream)


class UDPSocket(UnreliableObjectStream[UDPPacketType], _SocketProvider[IPSockAddrType]):
    """
    Represents an unconnected UDP socket.

    Supports all relevant extra attributes from :class:`~SocketAttribute`.
    """

    async def sendto(self, data: bytes, host: str, port: int) -> None:
        """Alias for :meth:`~.UnreliableObjectSendStream.send` ((data, (host, port)))."""
        return await self.send((data, (host, port)))


class ConnectedUDPSocket(UnreliableObjectStream[bytes], _SocketProvider[IPSockAddrType]):
    """
    Represents an connected UDP socket.

    Supports all relevant extra attributes from :class:`~SocketAttribute`.
    """
