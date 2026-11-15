from collections.abc import Generator
from contextlib import contextmanager
from typing import Self

from anyio import ContextManagerMixin


class SuperclassContextManager(ContextManagerMixin):
    @contextmanager
    def __contextmanager__(self) -> Generator[Self]:
        print("superclass entered")
        try:
            yield self
        finally:
            print("superclass exited")


class SubclassContextManager(SuperclassContextManager):
    @contextmanager
    def __contextmanager__(self) -> Generator[Self]:
        print("subclass entered")
        try:
            with super().__contextmanager__():
                yield self
        finally:
            print("subclass exited")
