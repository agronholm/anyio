import asyncio
from types import TracebackType
from typing import Self

import anyio


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
    async with anyio.create_task_group() as tg:
        tg.start_soon(handle_resource, Resource())
        tg.cancel_scope.cancel()


# Output: "closed"
asyncio.run(main())
