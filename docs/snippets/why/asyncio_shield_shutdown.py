import asyncio
import signal


async def finalizer() -> None:
    await asyncio.sleep(1)
    print("Finalizer done")


async def main() -> None:
    ...  # the business logic goes here
    # simulate ctrl+C
    asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)
    await asyncio.shield(finalizer())


# Prints a traceback containing a KeyboardInterrupt and a CancelledError, but not the "Finalizer done" message
asyncio.run(main())
