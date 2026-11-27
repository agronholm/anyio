from anyio import open_process, run
from anyio.streams.text import TextReceiveStream


async def main() -> None:
    async with await open_process(["ps"]) as process:
        assert process.stdout is not None
        async for text in TextReceiveStream(process.stdout):
            print(text)


run(main)
