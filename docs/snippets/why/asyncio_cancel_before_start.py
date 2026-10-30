import asyncio
from types import TracebackType
from typing import Self


class Resource:
    async def __aenter__(self) -> Self:
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # Here would be the code that cleanly closes the resource
        print("closed")


async def handle_resource(resource: Resource) -> None:
    async with resource:
        ...


async def main() -> None:
    async with asyncio.TaskGroup() as tg:
        task = tg.create_task(handle_resource(Resource()))
        task.cancel()


# No output
asyncio.run(main())
