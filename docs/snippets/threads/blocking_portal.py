from anyio import run, to_thread
from anyio.from_thread import BlockingPortal


async def async_func() -> None:
    print("This runs on the event loop")


def sync_func_run_in_thread(portal: BlockingPortal) -> None:
    portal.call(async_func)


async def main() -> None:
    async with BlockingPortal() as portal:
        # Here the portal stays open until the worker thread has run the function
        await to_thread.run_sync(sync_func_run_in_thread, portal)


run(main)
