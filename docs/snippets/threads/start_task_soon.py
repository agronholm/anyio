from concurrent.futures import as_completed

from anyio import sleep
from anyio.from_thread import start_blocking_portal


async def long_running_task(index: int) -> str:
    await sleep(1)
    print(f"Task {index} running...")
    await sleep(index)
    return f"Task {index} return value"


with start_blocking_portal() as portal:
    futures = [portal.start_task_soon(long_running_task, i) for i in range(1, 5)]
    for future in as_completed(futures):
        print(future.result())
