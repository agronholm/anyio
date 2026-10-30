from collections.abc import AsyncGenerator
from contextlib import asynccontextmanager
from typing import Self

from anyio import AsyncContextManagerMixin


class SuperclassContextManager(AsyncContextManagerMixin):
    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        print("superclass entered")
        try:
            yield self
        finally:
            print("superclass exited")


class SubclassContextManager(SuperclassContextManager):
    @asynccontextmanager
    async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
        print("subclass entered")
        try:
            async with super().__asynccontextmanager__():
                yield self
        finally:
            print("subclass exited")
