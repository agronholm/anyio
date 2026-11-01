from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Self

from anyio import AsyncContextManagerMixin, create_task_group


class MyBetterContextManager(AsyncContextManagerMixin):
    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as task_group:
            # Still crashes, but at least now the task group is exited
            task_group.start_soon(self.my_background_func)
            yield self

    async def my_background_func(self, arg: int) -> None: ...
