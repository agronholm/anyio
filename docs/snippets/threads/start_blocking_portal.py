from anyio.from_thread import start_blocking_portal


async def async_func() -> None:
    print("This runs on the event loop")


with start_blocking_portal() as portal:
    portal.call(async_func)
