import time

from anyio import Event, from_thread, run, to_thread


def worker(event: Event) -> None:
    time.sleep(1)
    from_thread.run_sync(event.set)


async def main() -> None:
    event = Event()
    await to_thread.run_sync(worker, event)
    await event.wait()


run(main)
