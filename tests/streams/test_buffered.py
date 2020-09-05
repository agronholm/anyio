import pytest

from anyio import IncompleteRead, create_memory_object_stream
from anyio.streams.buffered import BufferedByteReceiveStream

pytestmark = pytest.mark.anyio


async def test_receive_exactly():
    send_stream, receive_stream = create_memory_object_stream(2)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b'abcd')
    await send_stream.send(b'efgh')
    result = await buffered_stream.receive_exactly(8)
    assert result == b'abcdefgh'
    assert isinstance(result, bytes)


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

    result = await buffered_stream.receive_until(b'de', 10)
    assert result == b'abc'
    assert isinstance(result, bytes)

    result = await buffered_stream.receive_until(b'h', 10)
    assert result == b'fg'
    assert isinstance(result, bytes)


async def test_receive_until_incomplete():
    send_stream, receive_stream = create_memory_object_stream(1)
    buffered_stream = BufferedByteReceiveStream(receive_stream)
    await send_stream.send(b'abcd')
    await send_stream.aclose()
    with pytest.raises(IncompleteRead):
        assert await buffered_stream.receive_until(b'de', 10)

    assert buffered_stream.buffer == b'abcd'
