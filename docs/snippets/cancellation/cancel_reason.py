from anyio import CancelScope, get_cancelled_exc_class, sleep


async def do_something() -> None:
    with CancelScope() as scope:
        scope.cancel("Testing cancellation")
        try:
            await sleep(1)
        except get_cancelled_exc_class() as exc:
            print(exc)  # Print the cancellation message
            raise  # Always re-raise cancellation exceptions!
