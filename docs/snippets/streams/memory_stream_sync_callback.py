from anyio.streams.memory import MemoryObjectSendStream


def synchronous_callback(send_stream: MemoryObjectSendStream[str]) -> None:
    with send_stream:
        send_stream.send_nowait("hello")
