from collections.abc import Generator
from contextlib import contextmanager
from typing import Self

from anyio import ContextManagerMixin


class MyContextManager(ContextManagerMixin):
    @contextmanager
    def __contextmanager__(self) -> Generator[Self]:
        print("entering context")
        yield self
        print("exiting context")
