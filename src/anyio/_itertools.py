from __future__ import annotations

import itertools
import operator
import sys
from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Awaitable,
    Callable,
    Iterable,
    Iterator,
)
from dataclasses import dataclass, field
from typing import Any, Generic, TypeVar, cast, overload

from ._core._synchronization import Lock
from .lowlevel import checkpoint

T = TypeVar("T")
R = TypeVar("R")
_tee_end = object()


@dataclass(eq=False)
class _IterableAsyncIterator(AsyncIterator[T]):
    iterator: Iterator[T]

    async def __anext__(self) -> T:
        try:
            return next(self.iterator)
        except StopIteration:
            raise StopAsyncIteration from None


def _iterate(iterable: Iterable[T] | AsyncIterable[T]) -> AsyncIterator[T]:
    if isinstance(iterable, AsyncIterator):
        return iterable

    if isinstance(iterable, AsyncIterable):
        return iterable.__aiter__()

    return _IterableAsyncIterator(iter(iterable))


@dataclass(eq=False)
class _TeeLink(Generic[T]):
    value: object | None = None
    next: _TeeLink[T] | None = None
    filled: bool = False


@dataclass(eq=False)
class _TeeState(Generic[T]):
    iterator: AsyncIterator[T]
    lock: Lock = field(default_factory=Lock)

    async def fill(self, link: _TeeLink[T]) -> None:
        if link.filled:
            return

        async with self.lock:
            if link.filled:
                return

            try:
                link.value = await self.iterator.__anext__()
            except StopAsyncIteration:
                link.value = _tee_end
            else:
                link.next = _TeeLink()

            link.filled = True


class _TeeAsyncIterator(AsyncIterator[T]):
    _state: _TeeState[T]
    _link: _TeeLink[T]
    _element_yielded: bool

    def __init__(
        self, iterable: Iterable[T] | AsyncIterable[T] | _TeeAsyncIterator[T]
    ) -> None:
        if isinstance(iterable, _TeeAsyncIterator):
            self._state = iterable._state
            self._link = iterable._link
        else:
            self._state = _TeeState(_iterate(iterable))
            self._link = _TeeLink()

        self._element_yielded = False

    async def __anext__(self) -> T:
        await self._state.fill(self._link)
        if self._link.value is _tee_end:
            if not self._element_yielded:
                await checkpoint()

            raise StopAsyncIteration

        self._element_yielded = True
        value = cast(T, self._link.value)
        next_link = self._link.next
        assert next_link is not None
        self._link = next_link
        return value


async def _operator_add(x: T, y: T) -> T:
    return operator.add(x, y)


async def accumulate(
    iterable: Iterable[T] | AsyncIterable[T],
    function: Callable[[T, T], Awaitable[T]] = _operator_add,
    *,
    initial: T | None = None,
) -> AsyncIterator[T]:
    iterator = _iterate(iterable)
    if initial is None:
        try:
            total = await iterator.__anext__()
        except StopAsyncIteration:
            await checkpoint()
            return
    else:
        total = initial

    yield total

    async for element in iterator:
        total = await function(total, element)
        yield total


async def batched(
    iterable: Iterable[T] | AsyncIterable[T], n: int, *, strict: bool = False
) -> AsyncIterator[tuple[T, ...]]:
    if n < 1:
        raise ValueError("n must be at least one")

    iterator = _iterate(iterable)

    while True:
        batch: list[T] = []
        for _ in range(n):
            try:
                batch.append(await iterator.__anext__())
            except StopAsyncIteration:
                if not batch:
                    await checkpoint()
                    return
                if strict:
                    raise ValueError("batched(): incomplete batch") from None

                yield tuple(batch)
                return

        yield tuple(batch)


class Chain:
    def __call__(self, *iterables: Iterable[T] | AsyncIterable[T]) -> AsyncIterator[T]:
        return self.from_iterable(iterables)

    async def from_iterable(
        self,
        iterables: (
            Iterable[Iterable[T] | AsyncIterable[T]]
            | AsyncIterable[Iterable[T] | AsyncIterable[T]]
        ),
    ) -> AsyncIterator[T]:
        element_yielded = False

        async for iterable in _iterate(iterables):
            async for element in _iterate(iterable):
                element_yielded = True
                yield element

        if not element_yielded:
            await checkpoint()


chain = Chain()


async def combinations(
    iterable: Iterable[T] | AsyncIterable[T], r: int
) -> AsyncIterator[tuple[T, ...]]:
    pool: list[T] = [element async for element in _iterate(iterable)]

    if r > len(pool):
        await checkpoint()
        return

    for combination in itertools.combinations(pool, r):
        yield combination


async def combinations_with_replacement(
    iterable: Iterable[T] | AsyncIterable[T], r: int
) -> AsyncIterator[tuple[T, ...]]:
    pool: list[T] = [element async for element in _iterate(iterable)]

    if r > len(pool):
        await checkpoint()
        return

    for combination in itertools.combinations_with_replacement(pool, r):
        yield combination


async def compress(
    data: Iterable[T] | AsyncIterable[T],
    selectors: Iterable[object] | AsyncIterable[object],
) -> AsyncIterator[T]:
    data_iterator = _iterate(data)
    selector_iterator = _iterate(selectors)
    element_yielded = False

    while True:
        try:
            datum = await data_iterator.__anext__()
            selector = await selector_iterator.__anext__()
        except StopAsyncIteration:
            if not element_yielded:
                await checkpoint()

            return

        if selector:
            element_yielded = True
            yield datum


async def count(start: int = 0, step: int = 1) -> AsyncIterator[int]:
    n = start
    while True:
        yield n
        n += step


async def cycle(iterable: Iterable[T] | AsyncIterable[T]) -> AsyncIterator[T]:
    saved: list[T] = []
    async for element in _iterate(iterable):
        yield element
        saved.append(element)

    if not saved:
        await checkpoint()
        return

    while True:
        for element in saved:
            yield element


async def dropwhile(
    predicate: Callable[[T], Awaitable[object]],
    iterable: Iterable[T] | AsyncIterable[T],
) -> AsyncIterator[T]:
    element_yielded = False
    dropping = True

    async for element in _iterate(iterable):
        if dropping and await predicate(element):
            continue

        dropping = False
        element_yielded = True
        yield element

    if not element_yielded:
        await checkpoint()


async def filterfalse(
    predicate: Callable[[T], Awaitable[object]],
    iterable: Iterable[T] | AsyncIterable[T],
) -> AsyncIterator[T]:
    element_yielded = False

    async for element in _iterate(iterable):
        if not await predicate(element):
            element_yielded = True
            yield element

    if not element_yielded:
        await checkpoint()


@overload
def groupby(
    iterable: Iterable[T] | AsyncIterable[T],
) -> AsyncIterator[tuple[T, list[T]]]: ...


@overload
def groupby(
    iterable: Iterable[T] | AsyncIterable[T],
    key: Callable[[T], Awaitable[R]],
) -> AsyncIterator[tuple[R, list[T]]]: ...


async def groupby(
    iterable: Iterable[T] | AsyncIterable[T],
    key: Callable[[T], Awaitable[object]] | None = None,
) -> AsyncIterator[tuple[object, list[T]]]:
    iterator = _iterate(iterable)
    try:
        element = await iterator.__anext__()
    except StopAsyncIteration:
        await checkpoint()
        return

    group_key = element if key is None else await key(element)
    values = [element]

    async for element in iterator:
        next_key = element if key is None else await key(element)
        if next_key != group_key:
            yield group_key, values
            group_key = next_key
            values = [element]
        else:
            values.append(element)

    yield group_key, values


@overload
def islice(
    iterable: Iterable[T] | AsyncIterable[T],
    stop: int | None,
    /,
) -> AsyncIterator[T]: ...


@overload
def islice(
    iterable: Iterable[T] | AsyncIterable[T],
    start: int | None,
    stop: int | None,
    step: int | None = 1,
    /,
) -> AsyncIterator[T]: ...


async def islice(
    iterable: Iterable[T] | AsyncIterable[T],
    *args: int | None,
) -> AsyncIterator[T]:
    if not args:
        raise TypeError("islice expected at least 2 arguments, got 1")
    if len(args) > 3:
        raise TypeError(f"islice expected at most 4 arguments, got {len(args) + 1}")

    slice_args = slice(*args)

    start_message = (
        "Indices for islice() must be None or an integer: 0 <= x <= sys.maxsize."
    )
    stop_message = (
        "Stop argument for islice() must be None or an integer: 0 <= x <= sys.maxsize."
    )
    step_message = "Step for islice() must be a positive integer or None."

    def normalize_index(value: object, message: str) -> int:
        try:
            index = operator.index(cast(Any, value))
        except TypeError:
            raise ValueError(message) from None

        if index < 0 or index > sys.maxsize:
            raise ValueError(message)

        return index

    start = (
        0
        if slice_args.start is None
        else normalize_index(slice_args.start, start_message)
    )
    stop = (
        None
        if slice_args.stop is None
        else normalize_index(slice_args.stop, stop_message)
    )
    step = (
        1 if slice_args.step is None else normalize_index(slice_args.step, step_message)
    )

    if step <= 0:
        raise ValueError(step_message)

    if stop == 0 or start == stop:
        await checkpoint()
        return

    iterator = _iterate(iterable)
    index = 0
    element_yielded = False

    while stop is None or index < stop:
        try:
            element = await iterator.__anext__()
        except StopAsyncIteration:
            if not element_yielded:
                await checkpoint()

            return

        if index >= start and (index - start) % step == 0:
            element_yielded = True
            yield element

        index += 1

    if not element_yielded:
        await checkpoint()


async def pairwise(
    iterable: Iterable[T] | AsyncIterable[T],
) -> AsyncIterator[tuple[T, T]]:
    iterator = _iterate(iterable)
    try:
        previous = await iterator.__anext__()
    except StopAsyncIteration:
        await checkpoint()
        return

    element_yielded = False
    async for element in iterator:
        element_yielded = True
        yield previous, element
        previous = element

    if not element_yielded:
        await checkpoint()


async def permutations(
    iterable: Iterable[T] | AsyncIterable[T], r: int | None = None
) -> AsyncIterator[tuple[T, ...]]:
    pool: list[T] = [element async for element in _iterate(iterable)]
    n = len(pool)
    if r is None:
        r = n
    elif not isinstance(r, int):
        raise TypeError("Expected int as r")
    elif r < 0:
        raise ValueError("r must be non-negative")

    if r > n:
        await checkpoint()
        return

    indices = list(range(n))
    cycles = list(range(n, n - r, -1))

    yield tuple(pool[index] for index in indices[:r])

    while n:
        for i in reversed(range(r)):
            cycles[i] -= 1
            if cycles[i] == 0:
                indices[i:] = indices[i + 1 :] + indices[i : i + 1]
                cycles[i] = n - i
            else:
                j = cycles[i]
                indices[i], indices[-j] = indices[-j], indices[i]
                yield tuple(pool[index] for index in indices[:r])
                break
        else:
            return


async def product(
    *iterables: Iterable[T] | AsyncIterable[T], repeat: int = 1
) -> AsyncGenerator[tuple[T, ...], None]:
    repeat = operator.index(repeat)
    if repeat < 0:
        raise ValueError("repeat argument cannot be negative")

    pools: list[tuple[T, ...]] = []
    for iterable in iterables:
        pool: list[T] = [element async for element in _iterate(iterable)]
        pools.append(tuple(pool))

    tuple_yielded = False
    for value in itertools.product(*pools, repeat=repeat):
        tuple_yielded = True
        yield value

    if not tuple_yielded:
        await checkpoint()


async def repeat(element: T, times: int | None = None) -> AsyncIterator[T]:
    if times is None:
        while True:
            yield element

    remaining = operator.index(cast(Any, times))
    if remaining <= 0:
        await checkpoint()
        return

    while remaining > 0:
        yield element
        remaining -= 1


async def starmap(
    function: Callable[..., Awaitable[R]],
    iterable: (
        Iterable[Iterable[object] | AsyncIterable[object]]
        | AsyncIterable[Iterable[object] | AsyncIterable[object]]
    ),
) -> AsyncIterator[R]:
    result_yielded = False

    async for args_iterable in _iterate(iterable):
        args = [element async for element in _iterate(args_iterable)]
        result_yielded = True
        yield await function(*args)

    if not result_yielded:
        await checkpoint()


def tee(
    iterable: Iterable[T] | AsyncIterable[T], n: int = 2
) -> tuple[AsyncIterator[T], ...]:
    n = operator.index(cast(Any, n))
    if n < 0:
        raise ValueError("n must be >= 0")
    if n == 0:
        return ()

    iterator = _TeeAsyncIterator(iterable)
    iterators: list[AsyncIterator[T]] = [iterator]
    iterators.extend(_TeeAsyncIterator(iterator) for _ in range(n - 1))
    return tuple(iterators)


async def takewhile(
    predicate: Callable[[T], Awaitable[object]],
    iterable: Iterable[T] | AsyncIterable[T],
) -> AsyncIterator[T]:
    element_yielded = False

    async for element in _iterate(iterable):
        if not await predicate(element):
            if not element_yielded:
                await checkpoint()

            return

        element_yielded = True
        yield element

    if not element_yielded:
        await checkpoint()


async def zip_longest(
    *iterables: Iterable[object] | AsyncIterable[object],
    fillvalue: object = None,
) -> AsyncIterator[tuple[object, ...]]:
    iterators = [_iterate(iterable) for iterable in iterables]
    num_active = len(iterators)
    if not num_active:
        await checkpoint()
        return

    active = [True] * num_active
    tuple_yielded = False

    while True:
        values: list[object] = []
        for index, iterator in enumerate(iterators):
            if not active[index]:
                values.append(fillvalue)
                continue

            try:
                value = await iterator.__anext__()
            except StopAsyncIteration:
                active[index] = False
                num_active -= 1
                if not num_active:
                    if not tuple_yielded:
                        await checkpoint()

                    return

                value = fillvalue

            values.append(value)

        tuple_yielded = True
        yield tuple(values)
