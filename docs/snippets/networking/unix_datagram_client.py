from anyio import create_connected_unix_datagram_socket, run


async def main() -> None:
    async with await create_connected_unix_datagram_socket(
        remote_path="/dev/log"
    ) as unix_dg:
        await unix_dg.send(b"Hi there!\n")


run(main)
