import os

from anyio import connect_unix, run


async def main() -> None:
    async with await connect_unix("/tmp/mysock") as client:
        _, fds = await client.receive_fds(0, 1)
        with os.fdopen(fds[0]) as file:
            print(file.read())


run(main)
