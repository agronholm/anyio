import socket

from anyio import create_udp_socket, run


async def main() -> None:
    async with await create_udp_socket(family=socket.AF_INET, local_port=1234) as udp:
        async for packet, (host, port) in udp:
            await udp.sendto(b"Hello, " + packet, host, port)


run(main)
