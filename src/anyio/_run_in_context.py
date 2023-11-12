"""
These utility functions exist to support anyio pytest plugin's context management

Do *not* use them outside of it, for the following reasons:

 * context_wrap/context_wrap_async are expected to be used only on respectively
   synchronous/asynchronous fixture and test functions, and they are not robust
   in the face of unusual ways in which such functions can theoretically be written;
 * The wrapping of coroutines by context_wrap_async is likely to have a noticeable
   overhead compared to the way that asyncio and trio integrate Context objects in
   their library APIs;
"""

from __future__ import annotations

from functools import wraps
from inspect import isasyncgenfunction, isgeneratorfunction
from types import TracebackType
from typing import (
    TYPE_CHECKING,
    Any,
    AsyncGenerator,
    Awaitable,
    Callable,
    Coroutine,
    Generator,
    Protocol,
    TypeVar,
    overload,
)

_T_co = TypeVar("_T_co", covariant=True)
_T_contra = TypeVar("_T_contra", contravariant=True)
_V_co = TypeVar("_V_co", covariant=True)

if TYPE_CHECKING:
    from typing_extensions import ParamSpec

    _P = ParamSpec("_P")


class ContextLike(Protocol):
    def run(
        self, func: Callable[_P, _V_co], /, *args: _P.args, **kwargs: _P.kwargs
    ) -> _V_co:
        raise NotImplementedError


class GeneratorWrapper(Generator[_T_co, _T_contra, _V_co]):
    _context: ContextLike
    _wrapped: Generator[_T_co, _T_contra, _V_co]

    def __init__(
        self, context: ContextLike, wrapped: Generator[_T_co, _T_contra, _V_co], /
    ) -> None:
        self._context = context
        self._wrapped = wrapped

    def send(self, value: _T_contra, /) -> _T_co:
        return self._context.run(self._wrapped.send, value)

    @overload
    def throw(
        self,
        typ: type[BaseException],
        val: object = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> _T_co:
        ...

    @overload
    def throw(
        self,
        val: BaseException,
        _: None = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> _T_co:
        ...

    def throw(
        self,
        tv: type[BaseException] | BaseException,
        v: object = None,
        tb: TracebackType | None = None,
        /,
    ) -> _T_co:
        if isinstance(tv, BaseException):
            return self._context.run(self._wrapped.throw, tv)
        else:
            return self._context.run(self._wrapped.throw, tv, v, tb)


class AwaitableWrapper(Awaitable[_V_co]):
    _context: ContextLike
    _wrapped: Awaitable[_V_co]

    def __init__(self, context: ContextLike, wrapped: Awaitable[_V_co], /) -> None:
        self._context = context
        self._wrapped = wrapped

    def __await__(self) -> Generator[Any, None, _V_co]:
        generator = self._context.run(self._wrapped.__await__)
        return GeneratorWrapper(self._context, generator)


class AsyncGeneratorWrapper(AsyncGenerator[_T_co, _T_contra]):
    _context: ContextLike
    _wrapped: AsyncGenerator[_T_co, _T_contra]

    def __init__(
        self, context: ContextLike, wrapped: AsyncGenerator[_T_co, _T_contra], /
    ) -> None:
        self._context = context
        self._wrapped = wrapped

    def asend(self, value: _T_contra, /) -> Awaitable[_T_co]:
        awaitable = self._context.run(self._wrapped.asend, value)
        return AwaitableWrapper(self._context, awaitable)

    @overload
    def athrow(
        self,
        typ: type[BaseException],
        val: object = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> Awaitable[_T_co]:
        ...

    @overload
    def athrow(
        self,
        val: BaseException,
        _: None = ...,
        tb: TracebackType | None = ...,
        /,
    ) -> Awaitable[_T_co]:
        ...

    def athrow(
        self,
        tv: type[BaseException] | BaseException,
        v: object = None,
        tb: TracebackType | None = None,
        /,
    ) -> Awaitable[_T_co]:
        if isinstance(tv, BaseException):
            awaitable = self._context.run(self._wrapped.athrow, tv)
        else:
            awaitable = self._context.run(self._wrapped.athrow, tv, v, tb)
        return AwaitableWrapper(self._context, awaitable)


@overload
def context_wrap(
    context: ContextLike, func: Callable[_P, Generator[_T_co, _T_contra, _V_co]], /
) -> Callable[_P, Generator[_T_co, _T_contra, _V_co]]:
    ...


@overload
def context_wrap(
    context: ContextLike, func: Callable[_P, _V_co], /
) -> Callable[_P, _V_co]:
    ...


def context_wrap(context: ContextLike, func: Callable[_P, Any], /) -> Callable[_P, Any]:
    if isgeneratorfunction(func):

        @wraps(func)
        def generator_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Generator:
            generator = context.run(func, *args, **kwargs)
            result = yield from GeneratorWrapper(context, generator)
            return result

        return generator_wrapper

    else:

        @wraps(func)
        def func_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            result = context.run(func, *args, **kwargs)
            return result

        return func_wrapper


@overload
def context_wrap_async(
    context: ContextLike, func: Callable[_P, AsyncGenerator[_T_co, _T_contra]], /
) -> Callable[_P, AsyncGenerator[_T_co, _T_contra]]:
    ...


@overload
def context_wrap_async(
    context: ContextLike, func: Callable[_P, Awaitable[_V_co]], /
) -> Callable[_P, Coroutine[_T_co, _T_contra, _V_co]]:
    ...


def context_wrap_async(
    context: ContextLike, func: Callable[_P, Any], /
) -> Callable[_P, Any]:
    if isasyncgenfunction(func):

        @wraps(func)
        def asyncgen_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> AsyncGenerator:
            asyncgen = context.run(func, *args, **kwargs)
            return AsyncGeneratorWrapper(context, asyncgen)

        return asyncgen_wrapper

    else:

        @wraps(func)
        async def coroutine_wrapper(*args: _P.args, **kwargs: _P.kwargs) -> Any:
            coro = context.run(func, *args, **kwargs)
            result = await AwaitableWrapper(context, coro)
            return result

        return coroutine_wrapper
