import sniffio
import trio

from anyio import sleep


async def main() -> None:
    print("Hello")
    await sleep(1)
    print("I'm running on", sniffio.current_async_library())


trio.run(main)
