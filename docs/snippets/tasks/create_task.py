from anyio import TaskHandle, create_task_group, run, sleep


async def sometask(num: int) -> str:
    await sleep(1)
    return str(num)


async def main() -> None:
    async with create_task_group() as tg:
        handles = [tg.create_task(sometask(num)) for num in range(5)]
        handles[1].cancel()
        print(await handles[2])

    print(
        "Tasks finished:",
        ", ".join(
            handle.return_value
            for handle in handles
            if handle.status is TaskHandle.Status.FINISHED
        ),
    )
    # Should print:
    #   2
    #   Tasks finished: 0, 2, 3, 4


run(main)
