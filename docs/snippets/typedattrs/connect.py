from anyio import connect_tcp
from anyio.abc import SocketAttribute, SocketStream
from anyio.streams.tls import TLSStream


async def connect(host: str, port: int, tls: bool) -> None:
    stream: SocketStream | TLSStream
    if tls:
        stream = await connect_tcp(host, port, tls=True)
    else:
        stream = await connect_tcp(host, port, tls=False)

    print("Connected to", stream.extra(SocketAttribute.remote_address))
