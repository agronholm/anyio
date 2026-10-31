from anyio import TASK_STATUS_IGNORED, sleep
from anyio.abc import TaskStatus
from anyio.from_thread import start_blocking_portal


async def service_task(*, task_status: TaskStatus[str] = TASK_STATUS_IGNORED) -> str:
    task_status.started("STARTED")
    await sleep(1)
    return "DONE"


with start_blocking_portal() as portal:
    future, start_value = portal.start_task(service_task)
    print("Task has started with value", start_value)

    return_value = future.result()
    print("Task has finished with return value", return_value)
