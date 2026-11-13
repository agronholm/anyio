from anyio import NamedTemporaryFile, run


async def main() -> None:
    async with NamedTemporaryFile(mode="w+", delete=True) as f:
        print(f"Temporary file name: {f.name}")
        await f.write("Named temp file content")
        await f.seek(0)
        print(await f.read())


run(main)
