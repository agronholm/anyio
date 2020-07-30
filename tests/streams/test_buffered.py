import pytest

from anyio import create_memory_object_stream
from anyio.exceptions import IncompleteRead
from anyio.streams.buffered import BufferedByteReceiveStream

pytestmark = pytest.mark.anyio


async def test_receive_exactly():
    send_stream, receive_stream = create_memory_object_stream(2)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b'abcd')
    await send_stream.send(b'efgh')
    assert await buffered_stream.receive_exactly(8) == b'abcdefgh'


async def test_receive_exactly_incomplete():
    send_stream, receive_stream = create_memory_object_stream(1)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b'abcd')
    await send_stream.aclose()
    with pytest.raises(IncompleteRead):
        await buffered_stream.receive_exactly(8)


async def test_receive_until():
    send_stream, receive_stream = create_memory_object_stream(2)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b'abcd')
    await send_stream.send(b'efgh')
    assert await buffered_stream.receive_until(b'de', 10) == b'abc'
    assert await buffered_stream.receive_until(b'h', 10) == b'fg'


async def test_receive_until_incomplete():
    send_stream, receive_stream = create_memory_object_stream(1)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b'abcd')
    await send_stream.aclose()
    with pytest.raises(IncompleteRead):
        assert await buffered_stream.receive_until(b'de', 10)

    assert buffered_stream.buffer == b'abcd'
