from anyio import CancelScope, create_task_group, run, sleep


async def external_task() -> None:
    print("Started sleeping in the external task")
    await sleep(1)
    print("This line should never be seen")


async def main() -> None:
    async with create_task_group() as tg:
        with CancelScope(shield=True) as scope:
            tg.start_soon(external_task)
            tg.cancel_scope.cancel()
            print("Started sleeping in the host task")
            await sleep(1)
            print("Finished sleeping in the host task")


run(main)
