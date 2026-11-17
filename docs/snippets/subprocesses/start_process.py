import sys
from functools import partial
from subprocess import PIPE

from anyio import create_task_group, run, run_process


async def main() -> None:
    async with create_task_group() as task_group:
        process = await task_group.start(
            partial(
                run_process,
                [
                    sys.executable,
                    "-c",
                    "import sys; print(sys.stdin.readline().strip())",
                ],
                stdin=PIPE,
                stdout=None,
            )
        )
        print(f"Started process {process.pid}")
        assert process.stdin is not None
        await process.stdin.send(b"Hello from the parent!\n")
        await process.stdin.aclose()


run(main)
