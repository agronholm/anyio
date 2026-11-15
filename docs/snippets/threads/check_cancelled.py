import time

from anyio import from_thread, move_on_after, to_thread


def sync_function() -> None:
    while True:
        from_thread.check_cancelled()
        print("Not cancelled yet")
        time.sleep(1)


async def foo() -> None:
    with move_on_after(3):
        await to_thread.run_sync(sync_function)
