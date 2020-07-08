import platform
import sys

import pytest

from anyio import create_memory_object_stream
from anyio.streams.stapled import StapledObjectStream
from anyio.streams.text import TextReceiveStream, TextSendStream, TextStream

pytestmark = pytest.mark.anyio


async def test_receive():
    send_stream, receive_stream = create_memory_object_stream(1)
    text_stream = TextReceiveStream(receive_stream)
    await send_stream.send(b'\xc3\xa5\xc3\xa4\xc3')  # ends with half of the "ö" letter
    assert await text_stream.receive() == 'åä'

    # Send the missing byte for "ö"
    await send_stream.send(b'\xb6')
    assert await text_stream.receive() == 'ö'


async def test_send():
    send_stream, receive_stream = create_memory_object_stream(1)
    text_stream = TextSendStream(send_stream)
    await text_stream.send('åäö')
    assert await receive_stream.receive() == b'\xc3\xa5\xc3\xa4\xc3\xb6'


@pytest.mark.xfail(platform.python_implementation() == 'PyPy'
                   and sys.pypy_version_info < (7, 3, 2),
                   reason='PyPy has a bug in its incremental UTF-8 decoder (#3274)')
async def test_receive_encoding_error():
    send_stream, receive_stream = create_memory_object_stream(1)
    text_stream = TextReceiveStream(receive_stream, errors='replace')
    await send_stream.send(b'\xe5\xe4\xf6')  # "åäö" in latin-1
    assert await text_stream.receive() == '���'


async def test_send_encoding_error():
    send_stream, receive_stream = create_memory_object_stream(1)
    text_stream = TextSendStream(send_stream, encoding='iso-8859-1', errors='replace')
    await text_stream.send('€')
    assert await receive_stream.receive() == b'?'


async def test_bidirectional_stream():
    send_stream, receive_stream = create_memory_object_stream(1)
    stapled_stream = StapledObjectStream(send_stream, receive_stream)
    text_stream = TextStream(stapled_stream)

    await text_stream.send('åäö')
    assert await receive_stream.receive() == b'\xc3\xa5\xc3\xa4\xc3\xb6'

    await send_stream.send(b'\xc3\xa6\xc3\xb8')
    assert await text_stream.receive() == 'æø'
