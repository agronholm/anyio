from __future__ import annotations

import pytest

from anyio import (
    ClosedResourceError,
    EndOfStream,
    IncompleteRead,
    create_memory_object_stream,
)
from anyio.abc import ObjectStream, ObjectStreamConnectable
from anyio.streams.buffered import (
    BufferedByteReceiveStream,
    BufferedByteStream,
    BufferedConnectable,
)
from anyio.streams.stapled import StapledObjectStream


async def test_receive_exactly() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](2)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b"abcd")
    await send_stream.send(b"efgh")
    result = await buffered_stream.receive_exactly(8)
    assert result == b"abcdefgh"
    assert isinstance(result, bytes)

    send_stream.close()
    receive_stream.close()


async def test_receive_exactly_incomplete() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b"abcd")
    await send_stream.aclose()
    with pytest.raises(IncompleteRead):
        await buffered_stream.receive_exactly(8)

    send_stream.close()
    receive_stream.close()


async def test_receive_until() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](2)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b"abcd")
    await send_stream.send(b"efgh")

    result = await buffered_stream.receive_until(b"de", 10)
    assert result == b"abc"
    assert isinstance(result, bytes)

    result = await buffered_stream.receive_until(b"h", 10)
    assert result == b"fg"
    assert isinstance(result, bytes)

    send_stream.close()
    receive_stream.close()


async def test_receive_until_incomplete() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b"abcd")
    await send_stream.aclose()
    with pytest.raises(IncompleteRead):
        assert await buffered_stream.receive_until(b"de", 10)

    assert buffered_stream.buffer == b"abcd"

    send_stream.close()
    receive_stream.close()


async def test_buffered_stream() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    buffered_stream = BufferedByteStream(
        StapledObjectStream(send_stream, receive_stream)
    )
    await send_stream.send(b"abcd")
    assert await buffered_stream.receive_exactly(2) == b"ab"
    assert await buffered_stream.receive_exactly(2) == b"cd"

    # send_eof() should close only the sending end
    await buffered_stream.send_eof()
    pytest.raises(ClosedResourceError, send_stream.send_nowait, b"abc")
    pytest.raises(EndOfStream, receive_stream.receive_nowait)

    # aclose() closes the receive stream too
    await buffered_stream.aclose()
    pytest.raises(ClosedResourceError, receive_stream.receive_nowait)


async def test_buffered_connectable() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    memory_stream = StapledObjectStream(send_stream, receive_stream)

    class MemoryObjectConnectable(ObjectStreamConnectable[bytes]):
        async def connect(self) -> ObjectStream[bytes]:
            return memory_stream

    connectable = BufferedConnectable(MemoryObjectConnectable())
    async with await connectable.connect() as stream:
        assert isinstance(stream, BufferedByteStream)
        await stream.send(b"abcd")
        assert await stream.receive_exactly(2) == b"ab"
        assert await stream.receive_exactly(2) == b"cd"


async def test_feed_data() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    buffered_stream = BufferedByteStream(
        StapledObjectStream(send_stream, receive_stream)
    )
    send_stream.send_nowait(b"abcd")

    # The stream has not received the sent data yet, so b"xxx" should come out of the
    # buffer first, despite this order of data input
    buffered_stream.feed_data(b"xxx")
    buffered_stream.feed_data(b"foo")
    assert await buffered_stream.receive_exactly(10) == b"xxxfooabcd"
    await buffered_stream.aclose()
