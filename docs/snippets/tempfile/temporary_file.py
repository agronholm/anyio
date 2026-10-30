from anyio import TemporaryFile, run


async def main() -> None:
    async with TemporaryFile(mode="w+") as f:
        await f.write("Temporary file content")
        await f.seek(0)
        print(await f.read())  # Output: Temporary file content


run(main)
