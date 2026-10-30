from anyio import create_task_group, run, sleep


async def sometask(num: int) -> None:
    print("Task", num, "running")
    await sleep(1)
    print("Task", num, "finished")


async def main() -> None:
    async with create_task_group() as tg:
        for num in range(5):
            tg.start_soon(sometask, num)

    print("All tasks finished!")


run(main)
