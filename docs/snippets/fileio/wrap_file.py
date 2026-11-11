from anyio import run, wrap_file


async def main() -> None:
    with open("/some/path/somewhere") as f:
        async for line in wrap_file(f):
            print(line, end="")


run(main)
