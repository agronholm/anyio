from anyio import Future, FutureFailed, create_task_group, run


async def task1(future: Future[int]) -> None:
    future.exception = ValueError("Something went wrong!")


async def task2(future: Future[int]) -> None:
    future.cancel()


async def main() -> None:
    fut1, fut2 = Future[int](), Future[int]()
    async with create_task_group() as tg:
        tg.start_soon(task1, fut1)
        tg.start_soon(task2, fut2)

        try:
            await fut1
        except FutureFailed as exc:
            print(f"Caught: {exc.__cause__!r}")

        await fut2.wait()
        assert fut2.status is Future.Status.CANCELLED
        print(f"Status: {fut2.status.name}")


run(main)

# Output:
# Caught: ValueError('Something went wrong!')
# Status: CANCELLED
