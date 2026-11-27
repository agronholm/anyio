from anyio import Event, create_task_group, run


async def notify(event: Event) -> None:
    event.set()


async def main() -> None:
    event = Event()
    async with create_task_group() as tg:
        tg.start_soon(notify, event)
        await event.wait()
        print("Received notification!")


run(main)

# Output:
# Received notification!
