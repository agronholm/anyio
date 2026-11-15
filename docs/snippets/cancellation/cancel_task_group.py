from anyio import create_task_group, get_cancelled_exc_class, run, sleep


async def waiter(index: int) -> None:
    try:
        await sleep(1)
    except get_cancelled_exc_class():
        print(f"Waiter {index} cancelled")
        raise


async def taskfunc() -> None:
    async with create_task_group() as tg:
        # Start a couple tasks and wait until they are blocked
        tg.start_soon(waiter, 1)
        tg.start_soon(waiter, 2)
        await sleep(0.1)

        # Cancel the scope and exit the task group
        tg.cancel_scope.cancel()


run(taskfunc)

# Output:
# Waiter 1 cancelled
# Waiter 2 cancelled
