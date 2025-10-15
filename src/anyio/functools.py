from __future__ import annotations

__all__ = ("cache", "lru_cache", "reduce")

import functools
import sys
from collections import OrderedDict, defaultdict
from collections.abc import (
    AsyncIterable,
    Awaitable,
    Callable,
    Coroutine,
    Hashable,
    Iterable,
)
from functools import update_wrapper
from inspect import iscoroutinefunction
from typing import Any, Generic, NamedTuple, TypedDict, TypeVar, cast, overload

from ._core._synchronization import Lock
from .lowlevel import RunVar

if sys.version_info >= (3, 11):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

T = TypeVar("T")
S = TypeVar("S")
P = ParamSpec("P")
lru_cache_items = RunVar[defaultdict[Callable, tuple[OrderedDict, Lock]]](
    "lru_cache_items"
)


class _InitialMissingType:
    pass


initial_missing = _InitialMissingType()


class AsyncCacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int


class AsyncCacheParameters(TypedDict):
    maxsize: int | None
    typed: bool


class AsyncLRUCacheWrapper(Generic[P, T]):
    def __init__(
        self, func: Callable[..., Awaitable[T]], maxsize: int | None, typed: bool
    ):
        self.__wrapped__ = func
        self._hits: int = 0
        self._misses: int = 0
        self._maxsize = max(maxsize, 0) if maxsize is not None else None
        self._currsize: int = 0
        self._typed = typed
        update_wrapper(self, func)

    def cache_info(self) -> AsyncCacheInfo:
        return AsyncCacheInfo(self._hits, self._misses, self._maxsize, self._currsize)

    def cache_parameters(self) -> AsyncCacheParameters:
        return AsyncCacheParameters(maxsize=self._maxsize, typed=self._typed)

    def cache_clear(self) -> None:
        if cache := lru_cache_items.get(None):
            cache.pop(self.__wrapped__, None)
            self._hits = self._misses = self._currsize = 0

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        # Easy case first: if maxsize == 0, no caching is done
        if self._maxsize == 0:
            value = await self.__wrapped__(*args, **kwargs)
            self._misses += 1
            return value

        if self._typed:
            key: Hashable = tuple((type(arg), arg) for arg in args) + tuple(
                (type(val), key, val) for key, val in kwargs.items()
            )
        else:
            key = (args, frozenset(kwargs.items()))

        try:
            cache = lru_cache_items.get()
        except LookupError:
            cache = defaultdict(lambda: (OrderedDict(), Lock()))
            lru_cache_items.set(cache)

        cache_entry, lock = cache[self.__wrapped__]
        async with lock:
            try:
                value = cache_entry[key]
            except KeyError:
                self._misses += 1
                if self._maxsize is not None and len(cache_entry) >= self._maxsize:
                    cache_entry.popitem(last=False)
                else:
                    self._currsize += 1

                cache_entry[key] = value = await self.__wrapped__(*args, **kwargs)
            else:
                self._hits += 1
                cache_entry.move_to_end(key)

        return value


class _LRUCacheWrapper(Generic[T]):
    def __init__(self, maxsize: int | None, typed: bool):
        self._maxsize = maxsize
        self._typed = typed

    @overload
    def __call__(  # type: ignore[overload-overlap]
        self, func: Callable[P, Coroutine[Any, Any, T]], /
    ) -> AsyncLRUCacheWrapper[P, T]: ...

    @overload
    def __call__(
        self, func: Callable[..., T], /
    ) -> functools._lru_cache_wrapper[T]: ...

    def __call__(
        self, f: Callable[P, Coroutine[Any, Any, T]] | Callable[..., T], /
    ) -> AsyncLRUCacheWrapper[P, T] | functools._lru_cache_wrapper[T]:
        if iscoroutinefunction(f):
            return AsyncLRUCacheWrapper(f, self._maxsize, self._typed)

        return functools.lru_cache(maxsize=self._maxsize, typed=self._typed)(f)  # type: ignore[arg-type]


@overload
def cache(  # type: ignore[overload-overlap]
    func: Callable[P, Coroutine[Any, Any, T]], /
) -> AsyncLRUCacheWrapper[P, T]: ...


@overload
def cache(func: Callable[..., T], /) -> functools._lru_cache_wrapper[T]: ...


def cache(
    func: Callable[..., T] | Callable[P, Coroutine[Any, Any, T]], /
) -> AsyncLRUCacheWrapper[P, T] | functools._lru_cache_wrapper[T]:
    """
    A convenient shortcut for :func:`lru_cache` with ``maxsize=None``.

    This is the asynchronous equivalent to :func:`functools.cache`.

    """
    return lru_cache(maxsize=None)(func)


@overload
def lru_cache(
    *, maxsize: int | None = 128, typed: bool = False
) -> _LRUCacheWrapper: ...


@overload
def lru_cache(  # type: ignore[overload-overlap]
    func: Callable[P, Coroutine[Any, Any, T]], /
) -> AsyncLRUCacheWrapper[P, T]: ...


@overload
def lru_cache(func: Callable[..., T], /) -> functools._lru_cache_wrapper[T]: ...


def lru_cache(
    func: Callable[P, Coroutine[Any, Any, T]] | Callable[..., T] | None = None,
    /,
    *,
    maxsize: int | None = 128,
    typed: bool = False,
) -> AsyncLRUCacheWrapper[P, T] | functools._lru_cache_wrapper[T] | _LRUCacheWrapper:
    """
    An asynchronous version of :func:`functools.lru_cache`.

    If a synchronous function is passed, the standard library
    :func:`functools.lru_cache` is applied instead.

    .. note:: Caches and locks are managed on a per-event loop basis.

    """
    if func is None:
        return _LRUCacheWrapper(maxsize, typed)

    return _LRUCacheWrapper[T](maxsize, typed)(func)


@overload
async def reduce(
    function: Callable[[T, S], Awaitable[T]],
    iterable: Iterable[S] | AsyncIterable[S],
    /,
    initial: T,
) -> T: ...


@overload
async def reduce(
    function: Callable[[T, T], Awaitable[T]],
    iterable: Iterable[T] | AsyncIterable[T],
    /,
) -> T: ...


async def reduce(  # type: ignore[misc]
    function: Callable[[T, T], Awaitable[T]] | Callable[[T, S], Awaitable[T]],
    iterable: Iterable[T] | Iterable[S] | AsyncIterable[T] | AsyncIterable[S],
    /,
    initial: T | _InitialMissingType = initial_missing,
) -> T:
    """Asynchronous version of :func:`functools.reduce`."""
    element: Any
    if isinstance(iterable, AsyncIterable):
        async_it = iterable.__aiter__()
        if initial is initial_missing:
            value = cast(T, await async_it.__anext__())
        else:
            value = cast(T, initial)

        async for element in async_it:
            value = await function(value, element)
    else:
        it = iter(iterable)
        if initial is initial_missing:
            value = cast(T, next(it))
        else:
            value = cast(T, initial)

        for element in it:
            value = await function(value, element)

    return value
