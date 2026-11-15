from anyio import Lock, create_task_group, run, sleep


async def use_resource(tasknum: int, lock: Lock) -> None:
    async with lock:
        print("Task number", tasknum, "is now working with the shared resource")
        await sleep(1)


async def main() -> None:
    lock = Lock()
    async with create_task_group() as tg:
        for num in range(4):
            tg.start_soon(use_resource, num, lock)


run(main)

# Output:
# Task number 0 is now working with the shared resource
# Task number 1 is now working with the shared resource
# Task number 2 is now working with the shared resource
# Task number 3 is now working with the shared resource
