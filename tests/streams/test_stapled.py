from collections import deque
from dataclasses import InitVar, dataclass, field
from typing import Iterable

import pytest

from anyio import ClosedResourceError, EndOfStream
from anyio.abc import ByteReceiveStream, ByteSendStream, ObjectReceiveStream, ObjectSendStream
from anyio.streams.stapled import StapledByteStream, StapledObjectStream

pytestmark = pytest.mark.anyio


class TestStapledByteStream:
    @dataclass
    class DummyByteReceiveStream(ByteReceiveStream):
        data: InitVar[bytes]
        buffer: bytearray = field(init=False)
        _closed: bool = field(init=False, default=False)

        def __post_init__(self, data: bytes):
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

    @pytest.fixture
    def stapled(self):
        receive = self.DummyByteReceiveStream(b'hello, world')
        send = self.DummyByteSendStream()
        return StapledByteStream(send, receive)

    async def test_receive_send(self, stapled):
        assert await stapled.receive(3) == b'hel'
        assert await stapled.receive() == b'lo, world'
        assert await stapled.receive() == b''

        await stapled.send(b'how are you ')
        await stapled.send(b'today?')
        assert bytes(stapled.send_stream.buffer) == b'how are you today?'

    async def test_send_eof(self, stapled):
        await stapled.send_eof()
        await stapled.send_eof()
        with pytest.raises(ClosedResourceError):
            await stapled.send(b'world')

        assert await stapled.receive() == b'hello, world'

    async def test_aclose(self, stapled):
        await stapled.aclose()
        with pytest.raises(ClosedResourceError):
            await stapled.receive()
        with pytest.raises(ClosedResourceError):
            await stapled.send(b'')


class TestStapledObjectStream:
    @dataclass
    class DummyObjectReceiveStream(ObjectReceiveStream):
        data: InitVar[Iterable]
        buffer: deque = field(init=False)
        _closed: bool = field(init=False, default=False)

        def __post_init__(self, data: Iterable):
            self.buffer = deque(data)

        async def receive(self):
            if self._closed:
                raise ClosedResourceError
            if not self.buffer:
                raise EndOfStream

            return self.buffer.popleft()

        async def aclose(self) -> None:
            self._closed = True

    @dataclass
    class DummyObjectSendStream(ObjectSendStream):
        buffer: list = field(init=False, default_factory=list)
        _closed: bool = field(init=False, default=False)

        async def send(self, item) -> None:
            if self._closed:
                raise ClosedResourceError

            self.buffer.append(item)

        async def aclose(self) -> None:
            self._closed = True

    @pytest.fixture
    def stapled(self):
        receive = self.DummyObjectReceiveStream(['hello', 'world'])
        send = self.DummyObjectSendStream()
        return StapledObjectStream(send, receive)

    async def test_receive_send(self, stapled):
        assert await stapled.receive() == 'hello'
        assert await stapled.receive() == 'world'
        with pytest.raises(EndOfStream):
            await stapled.receive()

        await stapled.send('how are you ')
        await stapled.send('today?')
        assert stapled.send_stream.buffer == ['how are you ', 'today?']

    async def test_send_eof(self, stapled):
        await stapled.send_eof()
        await stapled.send_eof()
        with pytest.raises(ClosedResourceError):
            await stapled.send('world')

        assert await stapled.receive() == 'hello'
        assert await stapled.receive() == 'world'

    async def test_aclose(self, stapled):
        await stapled.aclose()
        with pytest.raises(ClosedResourceError):
            await stapled.receive()
        with pytest.raises(ClosedResourceError):
            await stapled.send(b'')
