from anyio import create_tcp_listener, run
from anyio.abc import SocketStream


async def handle(client: SocketStream) -> None:
    async with client:
        name = await client.receive(1024)
        await client.send(b"Hello, %s\n" % name)


async def main() -> None:
    listener = await create_tcp_listener(local_port=1234)
    await listener.serve(handle)


run(main)
