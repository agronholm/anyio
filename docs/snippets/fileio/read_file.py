from anyio import open_file, run


async def main() -> None:
    async with await open_file("/some/path/somewhere") as f:
        contents = await f.read()
        print(contents)


run(main)
