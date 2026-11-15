from anyio import create_memory_object_stream, run
from anyio.streams.buffered import BufferedByteReceiveStream


async def main() -> None:
    send, receive = create_memory_object_stream[bytes](4)
    buffered = BufferedByteReceiveStream(receive)
    for part in b"hel", b"lo, ", b"wo", b"rld!":
        await send.send(part)

    result = await buffered.receive_exactly(8)
    print(repr(result))

    result = await buffered.receive_until(b"!", 10)
    print(repr(result))


run(main)
