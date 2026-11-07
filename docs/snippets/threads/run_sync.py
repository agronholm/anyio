import time

from anyio import run, to_thread


async def main() -> None:
    await to_thread.run_sync(time.sleep, 5)


run(main)
