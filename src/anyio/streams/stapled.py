from dataclasses import dataclass
from typing import Any, Callable, Generic, Optional, Sequence, TypeVar

from ..abc import (
    ByteReceiveStream, ByteSendStream, ByteStream, Listener, ObjectReceiveStream, ObjectSendStream,
    ObjectStream, TaskGroup)

T_Item = TypeVar('T_Item')
T_Stream = TypeVar('T_Stream')


@dataclass
class StapledByteStream(ByteStream):
    """
    Combines two byte streams into a single, bidirectional byte stream.

    Extra attributes will be provided from both streams, with the receive stream providing the
    values in case of a conflict.

    :param ByteSendStream send_stream: the sending byte stream
    :param ByteReceiveStream receive_stream: the receiving byte stream
    """

    send_stream: ByteSendStream
    receive_stream: ByteReceiveStream

    async def receive(self, max_bytes: int = 65536) -> bytes:
        return await self.receive_stream.receive(max_bytes)

    async def send(self, item: bytes) -> None:
        await self.send_stream.send(item)

    async def send_eof(self) -> None:
        await self.send_stream.aclose()

    async def aclose(self) -> None:
        await self.send_stream.aclose()
        await self.receive_stream.aclose()

    @property
    def extra_attributes(self):
        return dict(**self.send_stream.extra_attributes, **self.receive_stream.extra_attributes)


@dataclass
class StapledObjectStream(Generic[T_Item], ObjectStream[T_Item]):
    """
    Combines two object streams into a single, bidirectional object stream.

    Extra attributes will be provided from both streams, with the receive stream providing the
    values in case of a conflict.

    :param ObjectSendStream send_stream: the sending object stream
    :param ObjectReceiveStream receive_stream: the receiving object stream
    """

    send_stream: ObjectSendStream[T_Item]
    receive_stream: ObjectReceiveStream[T_Item]

    async def receive(self) -> T_Item:
        return await self.receive_stream.receive()

    async def send(self, item: T_Item) -> None:
        await self.send_stream.send(item)

    async def send_eof(self) -> None:
        await self.send_stream.aclose()

    async def aclose(self) -> None:
        await self.send_stream.aclose()
        await self.receive_stream.aclose()

    @property
    def extra_attributes(self):
        return dict(**self.send_stream.extra_attributes, **self.receive_stream.extra_attributes)


@dataclass
class MultiListener(Generic[T_Stream], Listener[T_Stream]):
    """
    Combines multiple listeners into one, serving connections from all of them at once.

    Any MultiListeners in the given collection of listeners will have their listeners moved into
    this one.

    Extra attributes are provided from each listener, with each successive listener overriding any
    conflicting attributes from the previous one.

    :param listeners: listeners to serve
    :type listeners: Sequence[Listener[T_Stream]]
    """

    listeners: Sequence[Listener[T_Stream]]

    def __post_init__(self):
        listeners = []
        for listener in self.listeners:
            if isinstance(listener, MultiListener):
                listeners.extend(listener.listeners)
                del listener.listeners[:]
            else:
                listeners.append(listener)

        self.listeners = listeners

    async def serve(self, handler: Callable[[T_Stream], Any],
                    task_group: Optional[TaskGroup] = None) -> None:
        from .. import create_task_group

        # There is a mypy bug here
        async with create_task_group() as tg:  # type: ignore[attr-defined]
            for listener in self.listeners:
                await tg.spawn(listener.serve, handler, task_group)

    async def aclose(self) -> None:
        for listener in self.listeners:
            await listener.aclose()

    @property
    def extra_attributes(self):
        attributes = {}
        for listener in self.listeners:
            attributes.update(listener.extra_attributes)

        return attributes
