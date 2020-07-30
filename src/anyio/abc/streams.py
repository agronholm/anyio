from abc import abstractmethod
from typing import Generic, TypeVar, Union

from .resource import AsyncResource
from ..exceptions import EndOfStream, ClosedResourceError

T_Item = TypeVar('T_Item')
T_Stream = TypeVar('T_Stream', bound='AnyByteStream', covariant=True)


class UnreliableObjectReceiveStream(Generic[T_Item], AsyncResource):
    """
    An interface for receiving objects.

    This interface makes no guarantees that the received messages arrive in the order in which they
    were sent, or that no messages are missed.

    Asynchronously iterating over objects of this type will yield objects matching the given type
    parameter.
    """

    def __aiter__(self):
        return self

    async def __anext__(self) -> T_Item:
        try:
            return await self.receive()
        except EndOfStream:
            raise StopAsyncIteration

    @abstractmethod
    async def receive(self) -> T_Item:
        """
        Receive the next item.

        :raises anyio.exceptions.ClosedResourceError: if the receive stream has been explicitly
            closed
        :raises EndOfStream: if this stream has been closed from the other end
        :raises BrokenResourceError: if this stream has been rendered unusable due to external
            causes
        """


class UnreliableObjectSendStream(Generic[T_Item], AsyncResource):
    """
    An interface for sending objects.

    This interface makes no guarantees that the messages sent will reach the recipient(s) in the
    same order in which they were sent, or at all.
    """

    @abstractmethod
    async def send(self, item: T_Item) -> None:
        """
        Send an item to the peer(s).

        :param item: the item to send
        :raises anyio.exceptions.ClosedResourceError: if the send stream has been explicitly closed
        :raises BrokenResourceError: if this stream has been rendered unusable due to external
            causes
        """


class UnreliableObjectStream(Generic[T_Item], UnreliableObjectReceiveStream[T_Item],
                             UnreliableObjectSendStream[T_Item]):
    """
    A bidirectional message stream which does not guarantee the order or reliability of message
    delivery.
    """


class ObjectReceiveStream(Generic[T_Item], UnreliableObjectReceiveStream[T_Item]):
    """
    A receive message stream which guarantees that messages are received in the same order in
    which they were sent, and that no messages are missed.
    """


class ObjectSendStream(Generic[T_Item], UnreliableObjectSendStream[T_Item]):
    """
    A send message stream which guarantees that messages are delivered in the same order in which
    they were sent, without missing any messages in the middle.
    """


class ObjectStream(Generic[T_Item], ObjectReceiveStream[T_Item], ObjectSendStream[T_Item],
                   UnreliableObjectStream[T_Item]):
    """
    A bidirectional message stream which guarantees the order and reliability of message delivery.
    """

    @abstractmethod
    async def send_eof(self) -> None:
        """
        Send an end-of-file indication to the peer.

        You should not try to send any further data to this stream after calling this method.
        This method is idempotent (does nothing on successive calls).
        """


class ByteReceiveStream(AsyncResource):
    """
    An interface for receiving bytes from a single peer.

    Iterating this byte stream will yield a byte string of arbitrary length, but no more than
    65536 bytes.
    """

    def __aiter__(self) -> 'ByteReceiveStream':
        return self

    async def __anext__(self) -> bytes:
        data = await self.receive()
        if data:
            return data
        else:
            raise StopAsyncIteration

    @abstractmethod
    async def receive(self, max_bytes: int = 65536) -> bytes:
        """
        Receive at most ``max_bytes`` bytes from the peer.

        :param max_bytes: maximum number of bytes to receive
        :return: the received bytes
        """


class ByteSendStream(AsyncResource):
    """An interface for sending bytes to a single peer."""

    @abstractmethod
    async def send(self, item: bytes) -> None:
        """
        Send the given bytes to the peer.

        :param item: the bytes to send
        """


class ByteStream(ByteReceiveStream, ByteSendStream):
    """A bidirectional byte stream."""

    @abstractmethod
    async def send_eof(self) -> None:
        """
        Send an end-of-file indication to the peer.

        You should not try to send any further data to this stream after calling this method.
        This method is idempotent (does nothing on successive calls).
        """


#: type alias for all unreliable bytes-oriented receive streams
AnyUnreliableByteReceiveStream = Union[UnreliableObjectReceiveStream[bytes], ByteReceiveStream]
#: type alias for all unreliable bytes-oriented send streams
AnyUnreliableByteSendStream = Union[UnreliableObjectSendStream[bytes], ByteSendStream]
#: type alias for all unreliable bytes-oriented streams
AnyUnreliableByteStream = Union[UnreliableObjectStream[bytes], ByteStream]
#: type alias for all bytes-oriented receive streams
AnyByteReceiveStream = Union[ObjectReceiveStream[bytes], ByteReceiveStream]
#: type alias for all bytes-oriented send streams
AnyByteSendStream = Union[ObjectSendStream[bytes], ByteSendStream]
#: type alias for all bytes-oriented streams
AnyByteStream = Union[ObjectStream[bytes], ByteStream]


class Listener(Generic[T_Stream], AsyncResource):
    """
    An interface for objects that let you accept incoming connections.

    Asynchronously iterating over this object will yield streams matching the type parameter
    given for this interface.
    """

    def __aiter__(self):
        return self

    async def __anext__(self) -> T_Stream:
        try:
            return await self.accept()
        except ClosedResourceError:
            raise StopAsyncIteration

    @abstractmethod
    async def accept(self) -> T_Stream:
        """Accept an incoming connection."""
