from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Self

from anyio import AsyncContextManagerMixin


class MyAsyncContextManager(AsyncContextManagerMixin):
    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        print("entering context")
        yield self
        print("exiting context")
