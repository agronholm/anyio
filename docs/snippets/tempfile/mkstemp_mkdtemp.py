import os

from anyio import gettempdir, mkdtemp, mkstemp, run


async def main() -> None:
    fd, path = await mkstemp(suffix=".txt", prefix="mkstemp_", text=True)
    print(f"Created temp file: {path}")

    temp_dir = await mkdtemp(prefix="mkdtemp_")
    print(f"Created temp dir: {temp_dir}")

    print(f"Default temp dir: {await gettempdir()}")

    os.close(fd)
    os.remove(path)


run(main)
