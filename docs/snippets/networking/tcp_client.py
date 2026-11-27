from anyio import connect_tcp, run


async def main() -> None:
    async with await connect_tcp("hostname", 1234) as client:
        await client.send(b"Client\n")
        response = await client.receive()
        print(response)


run(main)
