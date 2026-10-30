from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Self

from anyio import AsyncContextManagerMixin, create_task_group


class MyAsyncContextManager(AsyncContextManagerMixin):
    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        async with create_task_group() as tg:
            ...  # launch tasks
            yield self
