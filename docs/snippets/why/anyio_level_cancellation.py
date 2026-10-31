import asyncio

import anyio


async def sleeper() -> None:
    try:
        await asyncio.sleep(1)
    except BaseException:
        pass  # the first cancellation is caught here

    # This will raise another CancelledError
    await asyncio.sleep(float("inf"))


async def main() -> None:
    async with anyio.create_task_group() as tg:
        tg.start_soon(sleeper)
        await asyncio.sleep(0)  # ensure that the task reaches the first sleep()
        tg.cancel_scope.cancel()

    print("done")


# Output: "done"
asyncio.run(main())
