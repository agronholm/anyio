from anyio import CapacityLimiter, create_task_group, run, sleep


async def use_resource(tasknum: int, limiter: CapacityLimiter) -> None:
    async with limiter:
        print(f"Task number {tasknum} is now working with the shared resource")
        await sleep(1)


async def main() -> None:
    limiter = CapacityLimiter(2)
    async with create_task_group() as tg:
        for num in range(10):
            tg.start_soon(use_resource, num, limiter)


run(main)

# Output:
# Task number 0 is now working with the shared resource
# Task number 1 is now working with the shared resource
# Task number 2 is now working with the shared resource
# Task number 3 is now working with the shared resource
# Task number 4 is now working with the shared resource
# Task number 5 is now working with the shared resource
# Task number 6 is now working with the shared resource
# Task number 7 is now working with the shared resource
# Task number 8 is now working with the shared resource
# Task number 9 is now working with the shared resource
