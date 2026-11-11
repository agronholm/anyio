from anyio import TASK_STATUS_IGNORED, create_task_group, run, sleep
from anyio.abc import TaskStatus


async def start_some_service(
    port: int, *, task_status: TaskStatus[int] = TASK_STATUS_IGNORED
) -> int:
    task_status.started(port)
    await sleep(10)
    return 42


async def main() -> None:
    async with create_task_group() as tg:
        handle = await tg.start(start_some_service, 5000, return_handle=True)
        print(f"Service started on port {handle.start_value}")
        handle.cancel()
        await handle.wait()


run(main)
