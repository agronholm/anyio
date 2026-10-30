from anyio import connect_unix, run


async def main() -> None:
    async with await connect_unix("/tmp/mysock") as client:
        await client.send(b"Client\n")
        response = await client.receive(1024)
        print(response)


run(main)
