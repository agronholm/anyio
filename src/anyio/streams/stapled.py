from dataclasses import dataclass
from typing import TypeVar, Generic

from ..abc import (
    ByteReceiveStream, ByteStream, ByteSendStream, ObjectStream, ObjectReceiveStream,
    ObjectSendStream)

T_Item = TypeVar('T_Item')


@dataclass
class StapledByteStream(ByteStream):
    """
    Combines two byte streams into a single, bidirectional byte stream.

    :param ByteSendStream send_stream: the sending byte stream
    :param ByteReceiveStream receive_stream: the receiving byte stream
    """

    send_stream: ByteSendStream
    receive_stream: ByteReceiveStream

    async def receive(self, max_bytes: int = 65536) -> bytes:
        return await self.receive_stream.receive(max_bytes)

    async def send(self, item: bytes) -> None:
        await self.send_stream.send(item)

    async def aclose(self) -> None:
        await self.send_stream.aclose()
        await self.receive_stream.aclose()


@dataclass
class StapledObjectStream(Generic[T_Item], ObjectStream[T_Item]):
    """
    Combines two object streams into a single, bidirectional object stream.

    :param ObjectSendStream send_stream: the sending object stream
    :param ObjectReceiveStream receive_stream: the receiving object stream
    """

    send_stream: ObjectSendStream[T_Item]
    receive_stream: ObjectReceiveStream[T_Item]

    async def receive(self) -> T_Item:
        return await self.receive_stream.receive()

    async def send(self, item: T_Item) -> None:
        await self.send_stream.send(item)

    async def aclose(self) -> None:
        await self.send_stream.aclose()
        await self.receive_stream.aclose()
