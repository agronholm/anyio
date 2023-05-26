from __future__ import annotations

from collections import deque
from dataclasses import InitVar, dataclass, field
from typing import Iterable, TypeVar

import pytest

from anyio import ClosedResourceError, EndOfStream
from anyio.abc import (
    ByteReceiveStream,
    ByteSendStream,
    ObjectReceiveStream,
    ObjectSendStream,
)
from anyio.streams.stapled import StapledByteStream, StapledObjectStream

pytestmark = pytest.mark.anyio


@dataclass
class DummyByteReceiveStream(ByteReceiveStream):
    data: InitVar[bytes]
    buffer: bytearray = field(init=False)
    _closed: bool = field(init=False, default=False)

    def __post_init__(self, data: bytes) -> None:
        self.buffer = bytearray(data)

    async def receive(self, max_bytes: int = 65536) -> bytes:
        if self._closed:
            raise ClosedResourceError

        data = bytes(self.buffer[:max_bytes])
        del self.buffer[:max_bytes]
        return data

    async def aclose(self) -> None:
        self._closed = True


@dataclass
class DummyByteSendStream(ByteSendStream):
    buffer: bytearray = field(init=False, default_factory=bytearray)
    _closed: bool = field(init=False, default=False)

    async def send(self, item: bytes) -> None:
        if self._closed:
            raise ClosedResourceError

        self.buffer.extend(item)

    async def aclose(self) -> None:
        self._closed = True


class TestStapledByteStream:
    @pytest.fixture
    def send_stream(self) -> DummyByteSendStream:
        return DummyByteSendStream()

    @pytest.fixture
    def receive_stream(self) -> DummyByteReceiveStream:
        return DummyByteReceiveStream(b"hello, world")

    @pytest.fixture
    def stapled(
        self, send_stream: DummyByteSendStream, receive_stream: DummyByteReceiveStream
    ) -> StapledByteStream:
        return StapledByteStream(send_stream, receive_stream)

    async def test_receive_send(
        self, stapled: StapledByteStream, send_stream: DummyByteSendStream
    ) -> None:
        assert await stapled.receive(3) == b"hel"
        assert await stapled.receive() == b"lo, world"
        assert await stapled.receive() == b""

        await stapled.send(b"how are you ")
        await stapled.send(b"today?")
        assert stapled.send_stream is send_stream
        assert bytes(send_stream.buffer) == b"how are you today?"

    async def test_send_eof(self, stapled: StapledByteStream) -> None:
        await stapled.send_eof()
        await stapled.send_eof()
        with pytest.raises(ClosedResourceError):
            await stapled.send(b"world")

        assert await stapled.receive() == b"hello, world"

    async def test_aclose(self, stapled: StapledByteStream) -> None:
        await stapled.aclose()
        with pytest.raises(ClosedResourceError):
            await stapled.receive()
        with pytest.raises(ClosedResourceError):
            await stapled.send(b"")


T_Item = TypeVar("T_Item")


@dataclass
class DummyObjectReceiveStream(ObjectReceiveStream[T_Item]):
    data: InitVar[Iterable[T_Item]]
    buffer: deque[T_Item] = field(init=False)
    _closed: bool = field(init=False, default=False)

    def __post_init__(self, data: Iterable[T_Item]) -> None:
        self.buffer = deque(data)

    async def receive(self) -> T_Item:
        if self._closed:
            raise ClosedResourceError
        if not self.buffer:
            raise EndOfStream

        return self.buffer.popleft()

    async def aclose(self) -> None:
        self._closed = True


@dataclass
class DummyObjectSendStream(ObjectSendStream[T_Item]):
    buffer: list[T_Item] = field(init=False, default_factory=list)
    _closed: bool = field(init=False, default=False)

    async def send(self, item: T_Item) -> None:
        if self._closed:
            raise ClosedResourceError

        self.buffer.append(item)

    async def aclose(self) -> None:
        self._closed = True


class TestStapledObjectStream:
    @pytest.fixture
    def receive_stream(self) -> DummyObjectReceiveStream[str]:
        return DummyObjectReceiveStream(["hello", "world"])

    @pytest.fixture
    def send_stream(self) -> DummyObjectSendStream[str]:
        return DummyObjectSendStream[str]()

    @pytest.fixture
    def stapled(
        self,
        receive_stream: DummyObjectReceiveStream[str],
        send_stream: DummyObjectSendStream[str],
    ) -> StapledObjectStream[str]:
        return StapledObjectStream(send_stream, receive_stream)

    async def test_receive_send(
        self, stapled: StapledObjectStream[str], send_stream: DummyObjectSendStream[str]
    ) -> None:
        assert await stapled.receive() == "hello"
        assert await stapled.receive() == "world"
        with pytest.raises(EndOfStream):
            await stapled.receive()

        await stapled.send("how are you ")
        await stapled.send("today?")
        assert stapled.send_stream is send_stream
        assert send_stream.buffer == ["how are you ", "today?"]

    async def test_send_eof(self, stapled: StapledObjectStream[str]) -> None:
        await stapled.send_eof()
        await stapled.send_eof()
        with pytest.raises(ClosedResourceError):
            await stapled.send("world")

        assert await stapled.receive() == "hello"
        assert await stapled.receive() == "world"

    async def test_aclose(self, stapled: StapledObjectStream[str]) -> None:
        await stapled.aclose()
        with pytest.raises(ClosedResourceError):
            await stapled.receive()
        with pytest.raises(ClosedResourceError):
            await stapled.send(b"")  # type: ignore[arg-type]
