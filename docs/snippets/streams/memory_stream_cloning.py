from anyio import create_memory_object_stream, create_task_group, run
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream


async def producer(name: str, send_stream: MemoryObjectSendStream[str]) -> None:
    async with send_stream:
        for number in range(3):
            await send_stream.send(f"{number} from producer {name}")


async def consumer(name: str, receive_stream: MemoryObjectReceiveStream[str]) -> None:
    async with receive_stream:
        async for item in receive_stream:
            print(f"consumer {name} received {item!r}")


async def main() -> None:
    send_stream, receive_stream = create_memory_object_stream[str]()
    async with create_task_group() as tg, send_stream, receive_stream:
        for name in "A", "B":
            tg.start_soon(producer, name, send_stream.clone())

        for name in "X", "Y":
            tg.start_soon(consumer, name, receive_stream.clone())


run(main)
