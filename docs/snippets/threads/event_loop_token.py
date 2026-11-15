from threading import Thread

from anyio import Event, from_thread, run
from anyio.lowlevel import EventLoopToken, current_token


def external_func(event: Event, token: EventLoopToken) -> None:
    # Enter the event loop using the given token to set the asynchronous event
    from_thread.run_sync(event.set, token=token)


async def main() -> None:
    event = Event()

    # Start a new thread, independent of AnyIO's worker threads
    thread = Thread(target=external_func, args=[event, current_token()])
    thread.start()

    # Wait for the external thread to set the event
    await event.wait()


run(main)
