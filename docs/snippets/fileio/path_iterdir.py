from anyio import Path, run


async def main() -> None:
    # Print the contents of every file (assumed to be text) in the directory /foo/bar
    dir_path = Path("/foo/bar")
    async for path in dir_path.iterdir():
        if await path.is_file():
            print(await path.read_text())
            print("---------------------")


run(main)
