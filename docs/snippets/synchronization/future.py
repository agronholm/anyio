from anyio import Future, create_task_group, run


async def task(future: Future[int], value: int) -> None:
    future.return_value = value


async def main() -> None:
    future = Future[int]()
    async with create_task_group() as tg:
        tg.start_soon(task, future, 5)
        result = await future

        print(f"Returned: {result}")


run(main)

# Output:
# Returned: 5
