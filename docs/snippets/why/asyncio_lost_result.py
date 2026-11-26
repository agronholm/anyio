import asyncio


async def receive(f: asyncio.Future[str]) -> None:
    print(await f)
    await asyncio.sleep(1)
    print("The task will be cancelled before this is printed")


async def main() -> None:
    f = asyncio.get_running_loop().create_future()
    task = asyncio.create_task(receive(f))
    await asyncio.sleep(0)  # make sure the task has started
    f.set_result("hello")
    task.cancel()

    # The "hello" result is lost due to the cancellation
    try:
        await task
    except asyncio.CancelledError:
        pass


# No output
asyncio.run(main())
