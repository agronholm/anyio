from anyio import create_task_group, move_on_after, run, sleep


async def main() -> None:
    async with create_task_group() as tg:
        with move_on_after(1) as scope:
            print("Starting sleep")
            await sleep(2)
            print("This should never be printed")

        # The cancelled_caught property will be True if timeout was reached
        print("Exited cancel scope, cancelled =", scope.cancelled_caught)


run(main)
