from __future__ import annotations

from types import TracebackType
from typing import (
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    ParamSpec,
    Protocol,
    TypeVar,
    overload,
)

T_co = TypeVar("T_co", covariant=True)
T_contra = TypeVar("T_contra", contravariant=True)
V_co = TypeVar("V_co", covariant=True)
P = ParamSpec("P")

class ContextLike(Protocol):
    def run(
        self, func: Callable[P, V_co], /, *args: P.args, **kwargs: P.kwargs
    ) -> V_co: ...

class GeneratorWrapper(Generator[T_co, T_contra, V_co]):
    _context: ContextLike
    _wrapped: Generator[T_co, T_contra, V_co]

    def __init__(
        self, context: ContextLike, wrapped: Generator[T_co, T_contra, V_co], /
    ) -> None: ...
    def send(self, value: T_contra, /) -> T_co: ...
    @overload
    def throw(
        self,
        typ: type[BaseException],
        val: object = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> T_co: ...
    @overload
    def throw(
        self,
        val: BaseException,
        _: None = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> T_co: ...

class AwaitableWrapper(Awaitable[V_co]):
    _context: ContextLike
    _wrapped: Awaitable[V_co]

    def __init__(self, context: ContextLike, wrapped: Awaitable[V_co], /) -> None: ...
    def __await__(self) -> Generator[Any, None, V_co]: ...

class AsyncGeneratorWrapper(AsyncGenerator[T_co, T_contra]):
    _context: ContextLike
    _wrapped: AsyncGenerator[T_co, T_contra]

    def __init__(
        self, context: ContextLike, wrapped: AsyncGenerator[T_co, T_contra], /
    ) -> None: ...
    def asend(self, value: T_contra, /) -> Awaitable[T_co]: ...
    @overload
    def athrow(
        self,
        typ: type[BaseException],
        val: object = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> Awaitable[T_co]: ...
    @overload
    def athrow(
        self,
        val: BaseException,
        _: None = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> Awaitable[T_co]: ...

@overload
def context_wrap(
    context: ContextLike, func: Callable[P, Generator[T_co, T_contra, V_co]], /
) -> Callable[P, Generator[T_co, T_contra, V_co]]: ...
@overload
def context_wrap(
    context: ContextLike, func: Callable[P, V_co], /
) -> Callable[P, V_co]: ...
@overload
def context_wrap_async(
    context: ContextLike, func: Callable[P, AsyncGenerator[T_co, T_contra]], /
) -> Callable[P, AsyncGenerator[T_co, T_contra]]: ...
@overload
def context_wrap_async(
    context: ContextLike, func: Callable[P, Awaitable[V_co]], /
) -> Callable[P, Coroutine[T_co, T_contra, V_co]]: ...
