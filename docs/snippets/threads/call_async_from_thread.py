from anyio import from_thread, run, sleep, to_thread


def blocking_function() -> None:
    from_thread.run(sleep, 5)


async def main() -> None:
    await to_thread.run_sync(blocking_function)


run(main)
