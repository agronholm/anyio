import signal

from anyio import CancelScope, create_task_group, open_signal_receiver, run


async def signal_handler(scope: CancelScope) -> None:
    with open_signal_receiver(signal.SIGINT, signal.SIGTERM) as signals:
        async for signum in signals:
            if signum == signal.SIGINT:
                print("Ctrl+C pressed!")
            else:
                print("Terminated!")

            scope.cancel()
            return


async def main() -> None:
    async with create_task_group() as tg:
        tg.start_soon(signal_handler, tg.cancel_scope)
        ...  # proceed with starting the actual application logic


run(main)
