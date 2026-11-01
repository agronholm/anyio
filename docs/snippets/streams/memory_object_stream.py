from anyio import create_memory_object_stream, create_task_group, run
from anyio.streams.memory import MemoryObjectReceiveStream


async def process_items(receive_stream: MemoryObjectReceiveStream[str]) -> None:
    async with receive_stream:
        async for item in receive_stream:
            print("received", item)


async def main() -> None:
    # The [str] specifies the type of the objects being passed through the
    # memory object stream. This is a bit of trick, as create_memory_object_stream
    # is actually a class masquerading as a function.
    send_stream, receive_stream = create_memory_object_stream[str]()
    async with create_task_group() as tg:
        tg.start_soon(process_items, receive_stream)
        async with send_stream:
            for num in range(10):
                await send_stream.send(f"number {num}")


run(main)
