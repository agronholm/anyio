import asyncio


async def sleeper() -> None:
    try:
        await asyncio.sleep(1)
    except BaseException:
        pass  # the first cancellation is caught here

    # This call will never return unless the task is cancelled again
    await asyncio.sleep(float("inf"))


async def main() -> None:
    async with asyncio.TaskGroup() as tg:
        task = tg.create_task(sleeper())
        await asyncio.sleep(0)  # ensure that the task reaches the first sleep()
        task.cancel()

    print("done")


# Execution hangs
asyncio.run(main())
