from anyio import connect_tcp, create_task_group, create_tcp_listener
from anyio.abc import SocketAttribute, SocketStream


async def test_echo() -> None:
    async def handle(client_stream: SocketStream) -> None:
        async with client_stream:
            payload = await client_stream.receive()
            await client_stream.send(payload[::-1])

    async with (
        await create_tcp_listener(local_host="127.0.0.1") as listener,
        create_task_group() as tg,
    ):
        tg.start_soon(listener.serve, handle)
        port = listener.extra(SocketAttribute.local_port)

        async with await connect_tcp("127.0.0.1", port) as stream:
            await stream.send(b"hello")
            assert await stream.receive() == b"olleh"

        tg.cancel_scope.cancel()
