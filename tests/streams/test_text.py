from __future__ import annotations

import platform
import sys

import pytest

from anyio import (
    BrokenResourceError,
    ClosedResourceError,
    EndOfStream,
    create_memory_object_stream,
)
from anyio.abc import ByteStream, ObjectStream, ObjectStreamConnectable
from anyio.streams.stapled import StapledObjectStream
from anyio.streams.text import (
    TextConnectable,
    TextReceiveStream,
    TextSendStream,
    TextStream,
)


async def test_receive() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    text_stream = TextReceiveStream(receive_stream)
    await send_stream.send(b"\xc3\xa5\xc3\xa4\xc3")  # ends with half of the "ö" letter
    assert await text_stream.receive() == "åä"

    # Send the missing byte for "ö"
    await send_stream.send(b"\xb6")
    assert await text_stream.receive() == "ö"

    send_stream.close()
    receive_stream.close()


async def test_send() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    text_stream = TextSendStream(send_stream)
    await text_stream.send("åäö")
    assert await receive_stream.receive() == b"\xc3\xa5\xc3\xa4\xc3\xb6"

    send_stream.close()
    receive_stream.close()


@pytest.mark.parametrize("stream_class", [TextSendStream, TextStream])
@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
async def test_send_keeps_encoding_state(
    stream_class: type[TextSendStream | TextStream], encoding: str
) -> None:
    send, receive = create_memory_object_stream[bytes](1)
    transport = StapledObjectStream(send, receive)
    stream = stream_class(transport, encoding=encoding)
    reader = TextReceiveStream(receive, encoding=encoding)
    async with stream:
        for text in ("first", "second", "日本語"):
            await stream.send(text)
            assert await reader.receive() == text


async def test_send_finalizes_encoding_on_close() -> None:
    send, receive = create_memory_object_stream[bytes](3)
    stream = TextSendStream(send, encoding="iso2022_jp")
    async with stream, receive:
        await stream.send("日本")
        await stream.send("語")
        await stream.aclose()
        assert b"".join([chunk async for chunk in receive]) == "日本語".encode(
            "iso2022_jp"
        )
        await stream.aclose()
        with pytest.raises(ClosedResourceError):
            await stream.send("closed")


@pytest.mark.parametrize("encoding", ["utf-8-sig", "utf-16", "utf-32"])
async def test_close_unused_send_stream(encoding: str) -> None:
    send, receive = create_memory_object_stream[bytes](1)
    stream = TextSendStream(send, encoding=encoding)
    await stream.aclose()
    with pytest.raises(EndOfStream):
        await receive.receive()

    await stream.aclose()
    await receive.aclose()


async def test_send_updates_error_handler() -> None:
    send, receive = create_memory_object_stream[bytes](1)
    stream = TextSendStream(send, encoding="ascii", errors="replace")
    async with stream, receive:
        await stream.send("€")
        assert await receive.receive() == b"?"
        stream.errors = "strict"
        with pytest.raises(UnicodeEncodeError):
            await stream.send("€")


async def test_close_after_encoder_flush_fails() -> None:
    send, receive = create_memory_object_stream[bytes](1)
    stream = TextSendStream(send, encoding="iso2022_jp")
    await stream.send("日本")
    await receive.aclose()
    with pytest.raises(BrokenResourceError):
        await stream.aclose()

    assert send.statistics().open_send_streams == 0
    await stream.aclose()


async def test_send_eof_finalizes_encoding() -> None:
    class Transport(ByteStream):
        chunks: list[bytes]
        eof_sent = False
        closed = False

        def __init__(self) -> None:
            self.chunks = []

        async def send(self, item: bytes) -> None:
            assert not self.eof_sent
            self.chunks.append(item)

        async def send_eof(self) -> None:
            self.eof_sent = True

        async def receive(self, max_bytes: int = 65536) -> bytes:
            return "response".encode("iso2022_jp")

        async def aclose(self) -> None:
            self.closed = True

    transport = Transport()
    stream = TextStream(transport, encoding="iso2022_jp")
    await stream.send("日本")
    await stream.send("語")
    await stream.send_eof()
    assert b"".join(transport.chunks) == "日本語".encode("iso2022_jp")
    assert transport.eof_sent
    assert not transport.closed
    assert await stream.receive() == "response"
    with pytest.raises(ClosedResourceError):
        await stream.send("closed")

    await stream.aclose()
    assert transport.closed


@pytest.mark.xfail(
    platform.python_implementation() == "PyPy" and sys.pypy_version_info < (7, 3, 2),  # type: ignore[attr-defined]
    reason="PyPy has a bug in its incremental UTF-8 decoder (#3274)",
)
async def test_receive_encoding_error() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    text_stream = TextReceiveStream(receive_stream, errors="replace")
    await send_stream.send(b"\xe5\xe4\xf6")  # "åäö" in latin-1
    assert await text_stream.receive() == "���"

    send_stream.close()
    receive_stream.close()


async def test_send_encoding_error() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    text_stream = TextSendStream(send_stream, encoding="iso-8859-1", errors="replace")
    await text_stream.send("€")
    assert await receive_stream.receive() == b"?"

    send_stream.close()
    receive_stream.close()


async def test_bidirectional_stream() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    stapled_stream = StapledObjectStream(send_stream, receive_stream)
    text_stream = TextStream(stapled_stream)

    await text_stream.send("åäö")
    assert await receive_stream.receive() == b"\xc3\xa5\xc3\xa4\xc3\xb6"

    await send_stream.send(b"\xc3\xa6\xc3\xb8")
    assert await text_stream.receive() == "æø"
    assert text_stream.extra_attributes == {}

    send_stream.close()
    receive_stream.close()


async def test_text_connectable() -> None:
    send_stream, receive_stream = create_memory_object_stream[bytes](1)
    memory_stream = StapledObjectStream(send_stream, receive_stream)

    class MemoryConnectable(ObjectStreamConnectable[bytes]):
        async def connect(self) -> ObjectStream[bytes]:
            return memory_stream

    connectable = TextConnectable(MemoryConnectable())
    async with await connectable.connect() as stream:
        assert isinstance(stream, TextStream)
        await stream.send("hello")
        assert await stream.receive() == "hello"
