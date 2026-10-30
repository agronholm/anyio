import asyncio
import gc


async def shielded_task() -> None:
    fut = asyncio.get_running_loop().create_future()
    await fut


async def host_task() -> None:
    await asyncio.shield(shielded_task())


async def main() -> None:
    async with asyncio.TaskGroup() as tg:
        task = tg.create_task(host_task())
        await asyncio.sleep(0)  # allow the host task to start
        task.cancel()
        await asyncio.sleep(0)  # allow the cancellation to take effect on the host task
        gc.collect()


# Prints warning: Task was destroyed but it is pending!
asyncio.run(main())
