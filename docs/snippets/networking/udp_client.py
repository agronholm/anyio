from anyio import create_connected_udp_socket, run


async def main() -> None:
    async with await create_connected_udp_socket(
        remote_host="hostname", remote_port=1234
    ) as udp:
        await udp.send(b"Hi there!\n")


run(main)
