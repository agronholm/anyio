from anyio import Path, run


async def main() -> None:
    path = Path("/foo/bar")
    await path.write_bytes(b"hello, world")


run(main)
