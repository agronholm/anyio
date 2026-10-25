from anyio import connect_tcp
from anyio.abc import SocketAttribute


async def connect(host: str, port: int) -> None:
    stream = await connect_tcp(host, port)
    print("Connected to", stream.extra(SocketAttribute.remote_address))
