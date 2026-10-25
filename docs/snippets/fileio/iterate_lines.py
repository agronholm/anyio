from anyio import open_file, run


async def main() -> None:
    async with await open_file("/some/path/somewhere") as f:
        async for line in f:
            print(line, end="")


run(main)
