from __future__ import annotations

import math
import sys
from collections.abc import AsyncGenerator, Sequence
from typing import TypeVar
from warnings import warn

from .. import sleep
from ..abc import ObjectStream, ObjectStreamConnectable, ResourcePool, SocketAttribute
from ..abc._streams import ConnectionStrategy
from ..streams.memory import (
    MemoryObjectReceiveStream,
    MemoryObjectSendStream,
    MemoryObjectStreamState,
)
from ._exceptions import ConnectionFailed, TypedAttributeLookupError
from ._resources import aclose_forcefully
from ._tasks import create_task_group

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup

T_Item = TypeVar("T_Item")
T_co = TypeVar("T_co", covariant=True)


class create_memory_object_stream(
    tuple[MemoryObjectSendStream[T_Item], MemoryObjectReceiveStream[T_Item]],
):
    """
    Create a memory object stream.

    The stream's item type can be annotated like
    :func:`create_memory_object_stream[T_Item]`.

    :param max_buffer_size: number of items held in the buffer until ``send()`` starts
        blocking
    :param item_type: old way of marking the streams with the right generic type for
        static typing (does nothing on AnyIO 4)

        .. deprecated:: 4.0
          Use ``create_memory_object_stream[YourItemType](...)`` instead.
    :return: a tuple of (send stream, receive stream)

    """

    def __new__(  # type: ignore[misc]
        cls, max_buffer_size: float = 0, item_type: object = None
    ) -> tuple[MemoryObjectSendStream[T_Item], MemoryObjectReceiveStream[T_Item]]:
        if max_buffer_size != math.inf and not isinstance(max_buffer_size, int):
            raise ValueError("max_buffer_size must be either an integer or math.inf")
        if max_buffer_size < 0:
            raise ValueError("max_buffer_size cannot be negative")
        if item_type is not None:
            warn(
                "The item_type argument has been deprecated in AnyIO 4.0. "
                "Use create_memory_object_stream[YourItemType](...) instead.",
                DeprecationWarning,
                stacklevel=2,
            )

        state = MemoryObjectStreamState[T_Item](max_buffer_size)
        return (MemoryObjectSendStream(state), MemoryObjectReceiveStream(state))


class PooledConnection(ObjectStream[T_Item]):
    def __init__(self, connection: ObjectStream[T_Item], pool: ConnectionPool[T_Item]):
        self._stream = connection
        self._pool = pool

    async def send_eof(self) -> None:
        await self._stream.send_eof()

    async def receive(self) -> T_Item:
        return await self._stream.receive()

    async def send(self, item: T_Item) -> None:
        return await self._stream.send(item)

    async def aclose(self) -> None:
        self._pool.release(self)


class ConnectionPool(
    ObjectStreamConnectable[T_Item], ResourcePool[ObjectStream[T_Item]]
):
    def __init__(self, max_size: int, connectable: ObjectStreamConnectable[T_Item]):
        super().__init__(max_size)
        self.connectable = connectable

    async def connect(self) -> ObjectStream[T_Item]:
        """
        Acquire a connection from the pool.

        :return: an async context manager yielding a byte object stream

        """
        return await self.acquire()

    async def create_resource(self) -> ObjectStream[T_Item]:
        stream = await self.connectable.connect()
        return PooledConnection(stream, self)

    async def validate_resource(self, resource: ObjectStream[T_Item]) -> bool:
        try:
            if resource.extra(SocketAttribute.raw_socket).fileno() == -1:
                return False
        except TypedAttributeLookupError:
            pass

        return True


class HappyEyeballsStrategy(ConnectionStrategy):
    def __init__(self, delay: float = 0.25):
        self.delay = delay

    async def get_connectables(
        self, connectables: Sequence[ObjectStreamConnectable[T_Item]]
    ) -> AsyncGenerator[Sequence[ObjectStreamConnectable[T_Item]]]:
        for connectable in connectables:
            yield [connectable]
            await sleep(self.delay)


class MultiConnector(ObjectStreamConnectable[T_Item]):
    def __init__(
        self,
        *connectables: ObjectStreamConnectable[T_Item],
        strategy: ConnectionStrategy,
    ):
        if not connectables:
            raise ValueError("at least one connectable is required")

        self.connectables = connectables
        self.strategy = strategy

    async def connect(self) -> ObjectStream[T_Item]:
        stream: ObjectStream[T_Item] | None = None
        errors: list[ConnectionFailed] = []

        async def _connect(
            _connectable: ObjectStreamConnectable[T_Item],
            _errors: list[ConnectionFailed],  # this is here as a Ruff workaround
        ) -> None:
            nonlocal stream
            try:
                _stream = await _connectable.connect()
            except ConnectionFailed as exc:
                _errors.append(exc)
            else:
                if stream is not None:
                    stream = _stream
                    tg.cancel_scope.cancel()
                else:
                    await aclose_forcefully(_stream)

        iterator = self.strategy.get_connectables(self.connectables)
        try:
            async with create_task_group() as tg:
                async for connectables in iterator:
                    for connectable in connectables:
                        tg.start_soon(_connect, connectable, errors)

            if stream is not None:
                return stream
        finally:
            await iterator.aclose()

        excgrp = ExceptionGroup("all connections failed", errors)
        try:
            raise ConnectionFailed("all connections failed") from excgrp
        finally:
            del excgrp, errors
