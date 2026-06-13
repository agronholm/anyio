from __future__ import annotations

from collections.abc import Awaitable, Callable, Coroutine, Generator
from typing import Any, ParamSpec, TypeVar

T = TypeVar("T")
P = ParamSpec("P")


def return_non_coro_awaitable(
    func: Callable[P, Coroutine[Any, Any, T]],
) -> Callable[P, Awaitable[T]]:
    class Wrapper:
        def __init__(self, *args: P.args, **kwargs: P.kwargs) -> None:
            self.args = args
            self.kwargs = kwargs

        def __await__(self) -> Generator[Any, Any, T]:
            return func(*self.args, **self.kwargs).__await__()

    return Wrapper
