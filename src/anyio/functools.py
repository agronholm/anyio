from __future__ import annotations

__all__ = (
    "AsyncCacheInfo",
    "AsyncCacheParameters",
    "AsyncLRUCacheWrapper",
    "cache",
    "lru_cache",
    "reduce",
)

import functools
from collections import OrderedDict
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
from typing import (
    Any,
    Generic,
    NamedTuple,
    ParamSpec,
    TypedDict,
    TypeVar,
    cast,
    final,
    overload,
)
from weakref import WeakKeyDictionary

from ._core._eventloop import current_time
from ._core._synchronization import Lock
from .lowlevel import RunVar, checkpoint

T = TypeVar("T")
S = TypeVar("S")
P = ParamSpec("P")


class _LRUCacheState:
    __slots__ = "hits", "misses", "pending", "values"

    def __init__(self) -> None:
        self.hits = 0
        self.misses = 0
        # Cached values and their expiration times, least recently used first
        self.values: OrderedDict[Hashable, tuple[Any, float | None]] = OrderedDict()
        # Locks of the calls whose values are still being computed
        self.pending: dict[Hashable, Lock] = {}


lru_cache_items: RunVar[
    WeakKeyDictionary[AsyncLRUCacheWrapper[Any, Any], _LRUCacheState]
] = RunVar("lru_cache_items")


class _InitialMissingType:
    pass


initial_missing: _InitialMissingType = _InitialMissingType()


class AsyncCacheInfo(NamedTuple):
    hits: int
    misses: int
    maxsize: int | None
    currsize: int
    ttl: int | None


class AsyncCacheParameters(TypedDict):
    maxsize: int | None
    typed: bool
    always_checkpoint: bool
    ttl: int | None


class _LRUMethodWrapper(Generic[T]):
    def __init__(self, wrapper: AsyncLRUCacheWrapper[..., T], instance: object):
        self.__wrapper = wrapper
        self.__instance = instance

    def cache_info(self) -> AsyncCacheInfo:
        return self.__wrapper.cache_info()

    def cache_parameters(self) -> AsyncCacheParameters:
        return self.__wrapper.cache_parameters()

    def cache_clear(self) -> None:
        self.__wrapper.cache_clear()

    async def __call__(self, *args: Any, **kwargs: Any) -> T:
        if self.__instance is None:
            return await self.__wrapper(*args, **kwargs)

        return await self.__wrapper(self.__instance, *args, **kwargs)


@final
class AsyncLRUCacheWrapper(Generic[P, T]):
    def __init__(
        self,
        func: Callable[P, Awaitable[T]],
        maxsize: int | None,
        typed: bool,
        always_checkpoint: bool,
        ttl: int | None,
    ):
        self.__wrapped__ = func
        self._maxsize = max(maxsize, 0) if maxsize is not None else None
        self._typed = typed
        self._always_checkpoint = always_checkpoint
        self._ttl = ttl
        update_wrapper(self, func)

    def _state(self) -> _LRUCacheState:
        try:
            states = lru_cache_items.get()
        except LookupError:
            states = WeakKeyDictionary()
            lru_cache_items.set(states)

        try:
            return states[self]
        except KeyError:
            state = states[self] = _LRUCacheState()
            return state

    def cache_info(self) -> AsyncCacheInfo:
        """
        Return the cache statistics for the current event loop.

        :raises NoEventLoopError: if no supported asynchronous event loop is running in
            the current thread

        """
        state = self._state()
        return AsyncCacheInfo(
            state.hits, state.misses, self._maxsize, len(state.values), self._ttl
        )

    def cache_parameters(self) -> AsyncCacheParameters:
        return {
            "maxsize": self._maxsize,
            "typed": self._typed,
            "always_checkpoint": self._always_checkpoint,
            "ttl": self._ttl,
        }

    def cache_clear(self) -> None:
        """
        Clear the cache and the cache statistics for the current event loop.

        :raises NoEventLoopError: if no supported asynchronous event loop is running in
            the current thread

        """
        state = self._state()
        state.values.clear()
        state.hits = state.misses = 0

    async def __call__(self, *args: P.args, **kwargs: P.kwargs) -> T:
        state = self._state()

        # Easy case first: if maxsize == 0, no caching is done
        if self._maxsize == 0:
            value = await self.__wrapped__(*args, **kwargs)
            state.misses += 1
            return value

        # The key is constructed as a flat tuple to avoid memory overhead
        key: tuple[Any, ...] = args
        if kwargs:
            # initial_missing is used as a separator
            key += (initial_missing,) + sum(kwargs.items(), ())

        if self._typed:
            key += tuple(type(arg) for arg in args)
            if kwargs:
                key += (initial_missing,) + tuple(type(val) for val in kwargs.values())

        if (entry := state.values.get(key)) is not None:
            value, expires_at = entry
            if expires_at is None or current_time() < expires_at:
                # The value was already cached
                state.hits += 1
                state.values.move_to_end(key)
                if self._always_checkpoint:
                    await checkpoint()

                return cast(T, value)

            del state.values[key]

        # Wait for any call that is already computing this value
        if (lock := state.pending.get(key)) is None:
            lock = Lock(fast_acquire=not self._always_checkpoint)
            state.pending[key] = lock

        try:
            async with lock:
                # Check if another task filled the cache while we were waiting
                if (entry := state.values.get(key)) is not None:
                    state.hits += 1
                    state.values.move_to_end(key)
                    return cast(T, entry[0])

                state.misses += 1
                value = await self.__wrapped__(*args, **kwargs)
                if self._maxsize is not None and len(state.values) >= self._maxsize:
                    state.values.popitem(last=False)

                expires_at = (
                    current_time() + self._ttl if self._ttl is not None else None
                )
                state.values[key] = value, expires_at
        finally:
            # Releasing the lock hands it over to the next waiting task, if any
            if not lock.locked():
                del state.pending[key]

        return value

    def __get__(
        self, instance: object, owner: type | None = None
    ) -> _LRUMethodWrapper[T]:
        wrapper = _LRUMethodWrapper(self, instance)
        update_wrapper(wrapper, self.__wrapped__)
        return wrapper


class _LRUCacheWrapper:
    def __init__(
        self, maxsize: int | None, typed: bool, always_checkpoint: bool, ttl: int | None
    ):
        self._maxsize = maxsize
        self._typed = typed
        self._always_checkpoint = always_checkpoint
        self._ttl = ttl

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
            return AsyncLRUCacheWrapper(
                f, self._maxsize, self._typed, self._always_checkpoint, self._ttl
            )

        return functools.lru_cache(maxsize=self._maxsize, typed=self._typed)(f)  # type: ignore[arg-type]


@overload
def cache(  # type: ignore[overload-overlap]
    func: Callable[P, Coroutine[Any, Any, T]], /
) -> AsyncLRUCacheWrapper[P, T]: ...


@overload
def cache(func: Callable[..., T], /) -> functools._lru_cache_wrapper[T]: ...


def cache(func: Callable[..., Any] | Callable[P, Coroutine[Any, Any, Any]], /) -> Any:
    """
    A convenient shortcut for :func:`lru_cache` with ``maxsize=None``.

    This is the asynchronous equivalent to :func:`functools.cache`.

    """
    return lru_cache(maxsize=None)(func)


@overload
def lru_cache(
    *,
    maxsize: int | None = ...,
    typed: bool = ...,
    always_checkpoint: bool = ...,
    ttl: int | None = ...,
) -> _LRUCacheWrapper: ...


@overload
def lru_cache(  # type: ignore[overload-overlap]
    func: Callable[P, Coroutine[Any, Any, T]], /
) -> AsyncLRUCacheWrapper[P, T]: ...


@overload
def lru_cache(func: Callable[..., T], /) -> functools._lru_cache_wrapper[T]: ...


def lru_cache(
    func: Callable[..., Coroutine[Any, Any, Any]] | Callable[..., Any] | None = None,
    /,
    *,
    maxsize: int | None = 128,
    typed: bool = False,
    always_checkpoint: bool = False,
    ttl: int | None = None,
) -> Any:
    """
    An asynchronous version of :func:`functools.lru_cache`.

    If a synchronous function is passed, the standard library
    :func:`functools.lru_cache` is applied instead.

    :param always_checkpoint: if ``True``, every call to the cached function will be
        guaranteed to yield control to the event loop at least once
    :param ttl: time in seconds after which to invalidate cache entries

    .. note:: Caches, locks and cache statistics are managed on a per-event loop basis,
        so ``cache_info()`` and ``cache_clear()`` raise :exc:`~anyio.NoEventLoopError` when
        called outside of an event loop.

    """
    if func is None:
        return _LRUCacheWrapper(maxsize, typed, always_checkpoint, ttl)

    if not callable(func):
        raise TypeError("the first argument must be callable")

    return _LRUCacheWrapper(maxsize, typed, always_checkpoint, ttl)(func)


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
    """
    Asynchronous version of :func:`functools.reduce`.

    :param function: a coroutine function that takes two arguments: the accumulated
        value and the next element from the iterable
    :param iterable: an iterable or async iterable
    :param initial: the initial value (if missing, the first element of the iterable is
        used as the initial value)

    """
    element: Any
    function_called = False
    if isinstance(iterable, AsyncIterable):
        async_it = iterable.__aiter__()
        if initial is initial_missing:
            try:
                value = cast(T, await async_it.__anext__())
            except StopAsyncIteration:
                raise TypeError(
                    "reduce() of empty sequence with no initial value"
                ) from None
        else:
            value = cast(T, initial)

        async for element in async_it:
            value = await function(value, element)
            function_called = True
    elif isinstance(iterable, Iterable):
        it = iter(iterable)
        if initial is initial_missing:
            try:
                value = cast(T, next(it))
            except StopIteration:
                raise TypeError(
                    "reduce() of empty sequence with no initial value"
                ) from None
        else:
            value = cast(T, initial)

        for element in it:
            value = await function(value, element)
            function_called = True
    else:
        raise TypeError("reduce() argument 2 must be an iterable or async iterable")

    # Make sure there is at least one checkpoint, even if an empty iterable and an
    # initial value were given
    if not function_called:
        await checkpoint()

    return value
