import sys
from contextlib import suppress
from functools import partial

from anyio import create_task_group, run, run_process, sleep
from anyio.abc import Process


async def deliver_cancel(process: Process) -> None:
    with suppress(ProcessLookupError):
        process.terminate()
        await sleep(5)
        process.kill()


async def main() -> None:
    async with create_task_group() as task_group:
        await task_group.start(
            partial(
                run_process,
                [sys.executable, "-c", "import time; time.sleep(60)"],
                deliver_cancel=deliver_cancel,
            )
        )
        task_group.cancel_scope.cancel()


run(main)
