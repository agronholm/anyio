from anyio import run
from anyio.streams.file import FileReadStream, FileWriteStream


async def main() -> None:
    path = "/tmp/testfile"
    async with await FileWriteStream.from_path(path) as stream:
        await stream.send(b"Hello, World!")

    async with await FileReadStream.from_path(path) as stream:
        async for chunk in stream:
            print(chunk.decode(), end="")

    print()


run(main)
