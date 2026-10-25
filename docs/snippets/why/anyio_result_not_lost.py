import asyncio

import anyio


async def receive(f: asyncio.Future[str]) -> None:
    print(await f)
    await asyncio.sleep(1)
    print("The task will be cancelled before this is printed")


async def main() -> None:
    f = asyncio.get_running_loop().create_future()
    async with anyio.create_task_group() as tg:
        tg.start_soon(receive, f)
        await asyncio.sleep(0)  # make sure the task has started
        f.set_result("hello")
        tg.cancel_scope.cancel()


# Output: "hello"
asyncio.run(main())
