from anyio import create_memory_object_stream, run
from anyio.streams.text import TextReceiveStream, TextSendStream


async def main() -> None:
    bytes_send, bytes_receive = create_memory_object_stream[bytes](1)
    text_send = TextSendStream(bytes_send)
    await text_send.send("åäö")
    result = await bytes_receive.receive()
    print(repr(result))

    text_receive = TextReceiveStream(bytes_receive)
    await bytes_send.send(result)
    text = await text_receive.receive()
    print(repr(text))


run(main)
