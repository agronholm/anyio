from anyio import Sequencer, create_task_group, run


async def worker(sequencer: Sequencer, position: int, message: str) -> None:
    async with sequencer(position):
        print(message)


async def main() -> None:
    sequencer = Sequencer()
    async with create_task_group() as tg:
        tg.start_soon(worker, sequencer, 2, "third")
        tg.start_soon(worker, sequencer, 1, "second")
        tg.start_soon(worker, sequencer, 0, "first")


run(main)
