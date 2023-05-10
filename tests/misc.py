from __future__ import annotations

import sys
from typing import Any, Awaitable, Callable, Generator, TypeVar

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

T = TypeVar("T")
P = ParamSpec("P")


def return_non_coro_awaitable(
    func: Callable[P, Awaitable[T]]
) -> Callable[P, Awaitable[T]]:
    class Wrapper:
        def __init__(self, *args: P.args, **kwargs: P.kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __await__(self) -> Generator[Any, None, T]:
            return func(*self.args, **self.kwargs).__await__()

    return Wrapper
