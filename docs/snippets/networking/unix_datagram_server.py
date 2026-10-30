from anyio import create_unix_datagram_socket, run


async def main() -> None:
    async with await create_unix_datagram_socket(local_path="/tmp/mysock") as unix_dg:
        async for packet, path in unix_dg:
            await unix_dg.sendto(b"Hello, " + packet, path)


run(main)
