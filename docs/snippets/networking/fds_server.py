from pathlib import Path

from anyio import create_unix_listener, run
from anyio.abc import SocketStream, UNIXSocketStream


async def handle(client: SocketStream) -> None:
    assert isinstance(client, UNIXSocketStream)
    async with client:
        with path.open("r") as file:
            await client.send_fds(b"this message is ignored", [file])


async def main() -> None:
    listener = await create_unix_listener("/tmp/mysock")
    await listener.serve(handle)


path = Path("/tmp/examplefile")
path.write_text("Test file")
run(main)
