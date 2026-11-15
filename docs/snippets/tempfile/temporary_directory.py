from anyio import TemporaryDirectory, run


async def main() -> None:
    async with TemporaryDirectory() as temp_dir:
        print(f"Temporary directory path: {temp_dir}")


run(main)
