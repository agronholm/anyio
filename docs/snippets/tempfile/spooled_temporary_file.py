from anyio import SpooledTemporaryFile, run


async def main() -> None:
    async with SpooledTemporaryFile(max_size=1024, mode="w+") as f:
        await f.write("Spooled temp file content")
        await f.seek(0)
        print(await f.read())


run(main)
