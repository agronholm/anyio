from anyio import Condition, create_task_group, run, sleep


async def listen(tasknum: int, condition: Condition) -> None:
    async with condition:
        await condition.wait()
        print("Woke up task number", tasknum)


async def main() -> None:
    condition = Condition()
    async with create_task_group() as tg:
        for tasknum in range(6):
            tg.start_soon(listen, tasknum, condition)

        await sleep(1)
        async with condition:
            condition.notify(1)

        await sleep(1)
        async with condition:
            condition.notify(2)

        await sleep(1)
        async with condition:
            condition.notify_all()


run(main)

# Output:
# Woke up task number 0
# Woke up task number 1
# Woke up task number 2
# Woke up task number 3
# Woke up task number 4
# Woke up task number 5
