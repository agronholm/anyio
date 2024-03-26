from __future__ import annotations

import pytest

from anyio import IncompleteRead, create_memory_object_stream
from anyio.streams.buffered import BufferedByteReceiveStream

pytestmark = pytest.mark.anyio


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
