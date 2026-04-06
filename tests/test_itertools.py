from __future__ import annotations

from collections.abc import AsyncGenerator, AsyncIterable, AsyncIterator, Iterable
from typing import Any, NoReturn, TypeVar, cast

import pytest

from anyio import CancelScope, get_cancelled_exc_class
from anyio._itertools import (
    accumulate,
    batched,
    chain,
    combinations,
    compress,
    count,
    cycle,
    dropwhile,
    filterfalse,
    groupby,
    islice,
    permutations,
    product,
    repeat,
    starmap,
    takewhile,
    tee,
    zip_longest,
)
from anyio.lowlevel import checkpoint

T = TypeVar("T")


async def collect(iterator: AsyncIterator[T]) -> list[T]:
    return [item async for item in iterator]


class TestAccumulate:
    async def test_iterable_no_initial(self) -> None:
        assert await collect(accumulate([1, 2, 3])) == [1, 3, 6]

    async def test_iterable_async_function_no_initial(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x * y

        assert await collect(accumulate([1, 2, 3], func)) == [1, 2, 6]

    async def test_iterable_has_initial(self) -> None:
        assert await collect(accumulate([1, 2, 3], initial=10)) == [10, 11, 13, 16]

    async def test_iterable_custom_function(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x * y

        assert await collect(accumulate([1, 2, 3], func, initial=2)) == [
            2,
            2,
            4,
            12,
        ]

    async def test_asynciter_no_initial(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3

        assert await collect(accumulate(asyncgen())) == [1, 3, 6]

    async def test_asynciter_async_function_no_initial(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x * y

        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 4

        assert await collect(accumulate(asyncgen(), func)) == [1, 2, 8]

    async def test_asynciter_has_initial(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x * y

        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3

        assert await collect(accumulate(asyncgen(), func, initial=2)) == [2, 2, 4, 12]

    async def test_empty_iterable_no_initial(self) -> None:
        assert await collect(accumulate([])) == []

    async def test_empty_async_iterable_no_initial(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        assert await collect(accumulate(AIter())) == []

    async def test_checkpoints_empty_iterable(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(accumulate([]))

    async def test_checkpoints_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(accumulate(AIter()))


class TestBatched:
    async def test_iterable(self) -> None:
        assert await collect(batched([1, 2, 3, 4, 5], 2)) == [(1, 2), (3, 4), (5,)]

    async def test_asynciter(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3
            yield 4
            yield 5

        assert await collect(batched(asyncgen(), 2)) == [(1, 2), (3, 4), (5,)]

    async def test_empty_iterable(self) -> None:
        assert await collect(batched([], 2)) == []

    async def test_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        assert await collect(batched(AIter(), 2)) == []

    async def test_strict_complete_batch(self) -> None:
        assert await collect(batched([1, 2, 3, 4], 2, strict=True)) == [(1, 2), (3, 4)]

    async def test_strict_incomplete_iterable(self) -> None:
        iterator = batched([1, 2, 3], 2, strict=True)
        assert await anext(iterator) == (1, 2)
        with pytest.raises(ValueError, match=r"batched\(\): incomplete batch"):
            await anext(iterator)

    async def test_strict_incomplete_async_iterable(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3

        iterator = batched(asyncgen(), 2, strict=True)
        assert await anext(iterator) == (1, 2)
        with pytest.raises(ValueError, match=r"batched\(\): incomplete batch"):
            await anext(iterator)

    async def test_invalid_n(self) -> None:
        with pytest.raises(ValueError, match="n must be at least one"):
            await anext(batched([1, 2, 3], 0))

    async def test_checkpoints_empty_iterable(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(batched([], 2))

    async def test_checkpoints_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(batched(AIter(), 2))


class TestChain:
    async def test_call_iterables(self) -> None:
        assert await collect(chain([1, 2], [3], [4, 5])) == [1, 2, 3, 4, 5]

    async def test_empty(self) -> None:
        assert await collect(chain()) == []

    async def test_call_mixed_iterables(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 3
            yield 4

        assert await collect(chain([1, 2], asyncgen(), [5])) == [1, 2, 3, 4, 5]

    async def test_from_iterable(self) -> None:
        iterables: list[Iterable[int] | AsyncIterable[int]] = [[1, 2], [3], [4, 5]]
        assert await collect(chain.from_iterable(iterables)) == [1, 2, 3, 4, 5]

    async def test_from_iterable_empty(self) -> None:
        assert await collect(chain.from_iterable([])) == []

    async def test_from_async_iterable(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 3
            yield 4

        async def outer() -> AsyncIterator[Iterable[int] | AsyncIterable[int]]:
            yield [1, 2]
            yield asyncgen()
            yield [5]

        assert await collect(chain.from_iterable(outer())) == [1, 2, 3, 4, 5]

    async def test_empty_inner_iterables(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            if False:
                yield 1

        assert await collect(chain([], asyncgen(), ())) == []

    async def test_skips_empty_iterables(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 3
            yield 4

        assert await collect(chain([1, 2], [], asyncgen(), ())) == [1, 2, 3, 4]

    async def test_propagates_inner_exception(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            raise RuntimeError("boom")

        iterator = chain(asyncgen())
        assert await anext(iterator) == 1
        with pytest.raises(RuntimeError, match="boom"):
            await anext(iterator)

    async def test_checkpoints_empty_arguments(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(chain())

    async def test_checkpoints_empty_outer_iterable(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(chain.from_iterable([]))

    async def test_checkpoints_only_empty_inner_iterables(self) -> None:
        async def outer() -> AsyncIterator[Iterable[int] | AsyncIterable[int]]:
            yield []
            yield ()

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(chain.from_iterable(outer()))


class TestCombinations:
    async def test_iterable(self) -> None:
        assert await collect(combinations([1, 2, 3], 2)) == [(1, 2), (1, 3), (2, 3)]

    async def test_iterable_stepwise(self) -> None:
        iterator = combinations([0, 1, 2, 3], 3)
        assert await anext(iterator) == (0, 1, 2)
        assert await anext(iterator) == (0, 1, 3)
        assert await anext(iterator) == (0, 2, 3)
        assert await anext(iterator) == (1, 2, 3)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    async def test_asynciter(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3

        assert await collect(combinations(asyncgen(), 2)) == [(1, 2), (1, 3), (2, 3)]

    async def test_asynciter_stepwise(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 0
            yield 1
            yield 2
            yield 3

        iterator = combinations(asyncgen(), 3)
        assert await anext(iterator) == (0, 1, 2)
        assert await anext(iterator) == (0, 1, 3)
        assert await anext(iterator) == (0, 2, 3)
        assert await anext(iterator) == (1, 2, 3)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    async def test_zero_length(self) -> None:
        assert await collect(combinations([1, 2, 3], 0)) == [()]

    async def test_empty_iterable_zero_length(self) -> None:
        assert await collect(combinations([], 0)) == [()]

    async def test_r_greater_than_pool(self) -> None:
        assert await collect(combinations([1, 2], 3)) == []

    async def test_negative_r(self) -> None:
        with pytest.raises(ValueError, match="r must be non-negative"):
            await anext(combinations([1, 2], -1))

    async def test_checkpoints_empty_result(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(combinations([], 1))


class TestCompress:
    async def test_iterable(self) -> None:
        assert await collect(compress("ABCDEF", [1, 0, 1, 0, 1, 1])) == [
            "A",
            "C",
            "E",
            "F",
        ]

    async def test_async_data(self) -> None:
        async def asyncgen() -> AsyncIterator[str]:
            yield "A"
            yield "B"
            yield "C"
            yield "D"

        assert await collect(compress(asyncgen(), [0, 1, 0, 1])) == ["B", "D"]

    async def test_async_selectors(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([1, 0, 1, 1])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        assert await collect(compress("ABCD", AIter())) == ["A", "C", "D"]

    async def test_shorter_selectors(self) -> None:
        iterator = compress("ABCD", [1, 0])
        assert await anext(iterator) == "A"
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    async def test_shorter_data(self) -> None:
        assert await collect(compress("AB", [1, 0, 1, 1])) == ["A"]

    async def test_no_selected_elements(self) -> None:
        assert await collect(compress("ABCD", [0, 0, 0, 0])) == []

    async def test_empty_data(self) -> None:
        assert await collect(compress([], [1, 0, 1])) == []

    async def test_empty_selectors(self) -> None:
        assert await collect(compress("ABCD", [])) == []

    async def test_checkpoints_empty_result(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(compress([], [1]))


class TestCount:
    async def test_defaults(self) -> None:
        iterator = cast(AsyncGenerator[int, None], count())
        try:
            assert await anext(iterator) == 0
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
        finally:
            await iterator.aclose()


class TestCycle:
    async def test_iterable(self) -> None:
        iterator = cast(AsyncGenerator[int, None], cycle([1, 2, 3]))
        try:
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
            assert await anext(iterator) == 3
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
            assert await anext(iterator) == 3
        finally:
            await iterator.aclose()

    async def test_asynciter(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2

        iterator = cast(AsyncGenerator[int, None], cycle(asyncgen()))
        try:
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
            assert await anext(iterator) == 1
        finally:
            await iterator.aclose()

    async def test_empty_iterable(self) -> None:
        assert await collect(cycle([])) == []

    async def test_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        assert await collect(cycle(AIter())) == []

    async def test_checkpoints_empty_iterable(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(cycle([]))

    async def test_checkpoints_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(cycle(AIter()))


class TestDropwhile:
    async def test_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 3

        assert await collect(dropwhile(predicate, [1, 2, 3, 4])) == [3, 4]

    async def test_asynciter(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 3

        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3
            yield 4

        assert await collect(dropwhile(predicate, asyncgen())) == [3, 4]

    async def test_no_elements_dropped(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        assert await collect(dropwhile(predicate, [1, 2, 3])) == [1, 2, 3]

    async def test_all_elements_dropped(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 4

        assert await collect(dropwhile(predicate, [1, 2, 3])) == []

    async def test_empty_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        assert await collect(dropwhile(predicate, [])) == []

    async def test_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        assert await collect(dropwhile(predicate, AIter())) == []

    async def test_checkpoints_empty_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(dropwhile(predicate, []))

    async def test_checkpoints_all_elements_dropped(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 4

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(dropwhile(predicate, [1, 2, 3]))


class TestFilterfalse:
    async def test_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value % 2 == 0

        assert await collect(filterfalse(predicate, [1, 2, 3, 4])) == [1, 3]

    async def test_asynciter(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value % 2 == 0

        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3
            yield 4

        assert await collect(filterfalse(predicate, asyncgen())) == [1, 3]

    async def test_no_elements_filtered_out(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return False

        assert await collect(filterfalse(predicate, [1, 2, 3])) == [1, 2, 3]

    async def test_all_elements_filtered_out(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return True

        assert await collect(filterfalse(predicate, [1, 2, 3])) == []

    async def test_empty_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return False

        assert await collect(filterfalse(predicate, [])) == []

    async def test_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        async def predicate(value: int) -> bool:
            await checkpoint()
            return False

        assert await collect(filterfalse(predicate, AIter())) == []

    async def test_checkpoints_empty_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return False

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(filterfalse(predicate, []))

    async def test_checkpoints_all_elements_filtered_out(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return True

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(filterfalse(predicate, [1, 2, 3]))


class TestGroupby:
    async def test_iterable(self) -> None:
        assert await collect(groupby([1, 1, 2, 2, 1])) == [
            (1, [1, 1]),
            (2, [2, 2]),
            (1, [1]),
        ]

    async def test_iterable_with_key(self) -> None:
        async def key(value: int) -> int:
            await checkpoint()
            return value % 2

        assert await collect(groupby([1, 3, 2, 4, 5, 7], key)) == [
            (1, [1, 3]),
            (0, [2, 4]),
            (1, [5, 7]),
        ]

    async def test_asynciter(self) -> None:
        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 1
            yield 2
            yield 2
            yield 1

        assert await collect(groupby(asyncgen())) == [
            (1, [1, 1]),
            (2, [2, 2]),
            (1, [1]),
        ]

    async def test_asynciter_with_key(self) -> None:
        async def key(value: int) -> int:
            await checkpoint()
            return value % 2

        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 3
            yield 2
            yield 4
            yield 5
            yield 7

        assert await collect(groupby(asyncgen(), key)) == [
            (1, [1, 3]),
            (0, [2, 4]),
            (1, [5, 7]),
        ]

    async def test_empty_iterable(self) -> None:
        assert await collect(groupby([])) == []

    async def test_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        assert await collect(groupby(AIter())) == []

    async def test_checkpoints_empty_iterable(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(groupby([]))

    async def test_checkpoints_empty_async_iterable(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(groupby(AIter()))


class TestIslice:
    async def test_stop_only(self) -> None:
        assert await collect(islice([0, 1, 2, 3, 4], 3)) == [0, 1, 2]

    async def test_none_start(self) -> None:
        assert await collect(islice([0, 1, 2, 3, 4], None, 3)) == [0, 1, 2]

    async def test_start_stop(self) -> None:
        assert await collect(islice([0, 1, 2, 3, 4], 1, 4)) == [1, 2, 3]

    async def test_start_stop_step(self) -> None:
        assert await collect(islice([0, 1, 2, 3, 4, 5], 1, 6, 2)) == [1, 3, 5]

    async def test_stop_none(self) -> None:
        assert await collect(islice([0, 1, 2, 3, 4], 1, None, 2)) == [1, 3]

    async def test_none_step(self) -> None:
        assert await collect(islice([0, 1, 2, 3, 4], 1, 4, None)) == [1, 2, 3]

    async def test_indexable_arguments(self) -> None:
        class Indexable:
            def __index__(self) -> int:
                return 2

        islice_any = cast(Any, islice)
        assert await collect(islice_any([0, 1, 2, 3, 4], Indexable())) == [0, 1]
        assert await collect(islice_any([0, 1, 2, 3, 4], 0, Indexable())) == [0, 1]
        assert await collect(islice_any([0, 1, 2, 3, 4], 0, 5, Indexable())) == [
            0,
            2,
            4,
        ]

    async def test_asynciter(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([0, 1, 2, 3, 4])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        assert await collect(islice(AIter(), 1, 4)) == [1, 2, 3]

    async def test_does_not_overconsume_iterator(self) -> None:
        iterator = iter([0, 1, 2, 3])
        assert await collect(islice(iterator, 2)) == [0, 1]
        assert next(iterator) == 2

    async def test_invalid_argument_count(self) -> None:
        islice_any = cast(Any, islice)

        with pytest.raises(TypeError, match="at least 2 arguments"):
            await anext(islice_any([]))

        with pytest.raises(TypeError, match="at most 4 arguments"):
            await anext(islice_any([], 1, 2, 3, 4))

    async def test_invalid_indices(self) -> None:
        islice_any = cast(Any, islice)

        with pytest.raises(
            ValueError,
            match=r"Indices for islice\(\) must be None or an integer",
        ):
            await anext(islice([1, 2, 3], -1, 2))

        with pytest.raises(
            ValueError,
            match=r"Stop argument for islice\(\) must be None or an integer",
        ):
            await anext(islice([1, 2, 3], 0, -1))

        with pytest.raises(
            ValueError, match=r"Step for islice\(\) must be a positive integer or None"
        ):
            await anext(islice([1, 2, 3], 0, 2, 0))

        with pytest.raises(
            ValueError,
            match=r"Indices for islice\(\) must be None or an integer",
        ):
            await anext(islice_any([1, 2, 3], "a", 2))

        with pytest.raises(
            ValueError,
            match=r"Stop argument for islice\(\) must be None or an integer",
        ):
            await anext(islice_any([1, 2, 3], 0, "a"))

        with pytest.raises(
            ValueError, match=r"Step for islice\(\) must be a positive integer or None"
        ):
            await anext(islice_any([1, 2, 3], 0, 2, "a"))

    async def test_empty_iterable(self) -> None:
        assert await collect(islice([], 3)) == []

    async def test_checkpoints_zero_stop(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(islice([1, 2, 3], 0))

    async def test_checkpoints_empty_iterable(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(islice([], 3))


class TestPermutations:
    async def test_iterable(self) -> None:
        assert await collect(permutations("ABCD", 2)) == [
            ("A", "B"),
            ("A", "C"),
            ("A", "D"),
            ("B", "A"),
            ("B", "C"),
            ("B", "D"),
            ("C", "A"),
            ("C", "B"),
            ("C", "D"),
            ("D", "A"),
            ("D", "B"),
            ("D", "C"),
        ]

    async def test_default_r(self) -> None:
        assert await collect(permutations(range(3))) == [
            (0, 1, 2),
            (0, 2, 1),
            (1, 0, 2),
            (1, 2, 0),
            (2, 0, 1),
            (2, 1, 0),
        ]

    async def test_asynciter(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([0, 1, 2])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        assert await collect(permutations(AIter(), 2)) == [
            (0, 1),
            (0, 2),
            (1, 0),
            (1, 2),
            (2, 0),
            (2, 1),
        ]

    async def test_zero_length(self) -> None:
        assert await collect(permutations("AB", 0)) == [()]

    async def test_r_greater_than_pool(self) -> None:
        assert await collect(permutations("AB", 3)) == []

    async def test_negative_r(self) -> None:
        with pytest.raises(ValueError, match="r must be non-negative"):
            await anext(permutations("AB", -1))

    async def test_invalid_r_type(self) -> None:
        permutations_any = cast(Any, permutations)
        with pytest.raises(TypeError, match="Expected int as r"):
            await anext(permutations_any("AB", "a"))

    async def test_checkpoints_empty_result(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(permutations("AB", 3))

    async def test_custom_start_and_step(self) -> None:
        iterator = cast(AsyncGenerator[int, None], count(10, -3))
        try:
            assert await anext(iterator) == 10
            assert await anext(iterator) == 7
            assert await anext(iterator) == 4
        finally:
            await iterator.aclose()


class TestProduct:
    async def test_iterables(self) -> None:
        assert await collect(product("AB", "xy")) == [
            ("A", "x"),
            ("A", "y"),
            ("B", "x"),
            ("B", "y"),
        ]

    async def test_repeat(self) -> None:
        assert await collect(product(range(2), repeat=3)) == [
            (0, 0, 0),
            (0, 0, 1),
            (0, 1, 0),
            (0, 1, 1),
            (1, 0, 0),
            (1, 0, 1),
            (1, 1, 0),
            (1, 1, 1),
        ]

    async def test_asynciter(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([0, 1])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        assert await collect(product(AIter(), "ab")) == [
            (0, "a"),
            (0, "b"),
            (1, "a"),
            (1, "b"),
        ]

    async def test_no_iterables(self) -> None:
        assert await collect(product()) == [()]

    async def test_zero_repeat(self) -> None:
        assert await collect(product("AB", repeat=0)) == [()]

    async def test_empty_pool(self) -> None:
        assert await collect(product([], "ab")) == []

    async def test_negative_repeat(self) -> None:
        with pytest.raises(ValueError, match="repeat argument cannot be negative"):
            await anext(product("AB", repeat=-1))

    async def test_invalid_repeat_type(self) -> None:
        product_any = cast(Any, product)
        with pytest.raises(TypeError, match="cannot be interpreted as an integer"):
            await anext(product_any("AB", repeat="a"))

    async def test_checkpoints_empty_result(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(product([], "ab"))


class TestRepeat:
    async def test_infinite(self) -> None:
        iterator = cast(AsyncGenerator[str, None], repeat("x"))
        try:
            assert await anext(iterator) == "x"
            assert await anext(iterator) == "x"
            assert await anext(iterator) == "x"
        finally:
            await iterator.aclose()

    async def test_finite(self) -> None:
        assert await collect(repeat("x", 3)) == ["x", "x", "x"]

    async def test_zero_times(self) -> None:
        assert await collect(repeat("x", 0)) == []

    async def test_negative_times(self) -> None:
        assert await collect(repeat("x", -1)) == []

    async def test_indexable_times(self) -> None:
        class Indexable:
            def __index__(self) -> int:
                return 2

        repeat_any = cast(Any, repeat)
        assert await collect(repeat_any("x", Indexable())) == ["x", "x"]

    async def test_invalid_times_type(self) -> None:
        repeat_any = cast(Any, repeat)
        with pytest.raises(TypeError, match="cannot be interpreted as an integer"):
            await anext(repeat_any("x", "a"))

    async def test_checkpoints_zero_times(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(repeat("x", 0))

    async def test_checkpoints_negative_times(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(repeat("x", -1))


class TestStarmap:
    async def test_iterable(self) -> None:
        async def func(a: int, b: int) -> int:
            await checkpoint()
            return a**b

        assert await collect(starmap(func, [(2, 5), (3, 2), (10, 3)])) == [
            32,
            9,
            1000,
        ]

    async def test_async_outer_iterable(self) -> None:
        async def func(a: int, b: int) -> int:
            await checkpoint()
            return a + b

        async def outer() -> AsyncIterator[Iterable[object] | AsyncIterable[object]]:
            yield (1, 2)
            yield (3, 4)

        assert await collect(starmap(func, outer())) == [3, 7]

    async def test_async_inner_iterable(self) -> None:
        async def func(a: int, b: int) -> int:
            await checkpoint()
            return a * b

        async def args_iterable(a: int, b: int) -> AsyncIterator[object]:
            yield a
            yield b

        assert await collect(
            starmap(func, [args_iterable(2, 5), args_iterable(3, 2)])
        ) == [
            10,
            6,
        ]

    async def test_empty_iterable(self) -> None:
        assert await collect(starmap(lambda: checkpoint(), [])) == []

    async def test_checkpoints_empty_iterable(self) -> None:
        async def func() -> None:
            await checkpoint()

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(starmap(func, []))


class TestTakewhile:
    async def test_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 5

        assert await collect(takewhile(predicate, [1, 4, 6, 3, 8])) == [1, 4]

    async def test_asynciter(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([1, 2, 3, 1])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 3

        assert await collect(takewhile(predicate, AIter())) == [1, 2]

    async def test_all_elements_taken(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 4

        assert await collect(takewhile(predicate, [1, 2, 3])) == [1, 2, 3]

    async def test_no_elements_taken(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        assert await collect(takewhile(predicate, [1, 2, 3])) == []

    async def test_empty_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        assert await collect(takewhile(predicate, [])) == []

    async def test_consumes_first_failing_element(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 5

        iterator = iter([1, 4, 6, 3, 8])
        assert await collect(takewhile(predicate, iterator)) == [1, 4]
        assert next(iterator) == 3

    async def test_checkpoints_empty_iterable(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(takewhile(predicate, []))

    async def test_checkpoints_no_elements_taken(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 0

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(takewhile(predicate, [1, 2, 3]))


class TestTee:
    async def test_iterable(self) -> None:
        iterator1, iterator2 = tee([1, 2, 3])
        assert await anext(iterator1) == 1
        assert await anext(iterator1) == 2
        assert await anext(iterator2) == 1
        assert await anext(iterator2) == 2
        assert await anext(iterator2) == 3
        with pytest.raises(StopAsyncIteration):
            await anext(iterator2)
        assert await anext(iterator1) == 3
        with pytest.raises(StopAsyncIteration):
            await anext(iterator1)

    async def test_asynciter(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([1, 2, 3])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        iterator1, iterator2 = tee(AIter())
        assert await collect(iterator1) == [1, 2, 3]
        assert await collect(iterator2) == [1, 2, 3]

    async def test_n_zero(self) -> None:
        assert tee([1, 2, 3], 0) == ()

    async def test_n_one_creates_peekable_iterator(self) -> None:
        (iterator,) = tee("abcdef", 1)
        assert await anext(iterator) == "a"

        (forked_iterator,) = tee(iterator, 1)
        assert await anext(forked_iterator) == "b"
        assert await anext(iterator) == "b"

    async def test_invalid_n(self) -> None:
        with pytest.raises(ValueError, match=r"n must be >= 0"):
            tee([1, 2, 3], -1)

        tee_any = cast(Any, tee)
        with pytest.raises(TypeError, match="cannot be interpreted as an integer"):
            tee_any([1, 2, 3], "a")

    async def test_checkpoints_empty_iterable(self) -> None:
        iterator: AsyncIterator[int]
        (iterator,) = tee(cast(list[int], []), 1)
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(iterator)


class TestZipLongest:
    async def test_iterables(self) -> None:
        assert await collect(zip_longest("ABCD", "xy", fillvalue="-")) == [
            ("A", "x"),
            ("B", "y"),
            ("C", "-"),
            ("D", "-"),
        ]

    async def test_default_fillvalue(self) -> None:
        assert await collect(zip_longest([1, 2], [10])) == [
            (1, 10),
            (2, None),
        ]

    async def test_asynciter(self) -> None:
        class AIter:
            def __init__(self) -> None:
                self._iterator = iter([1, 2, 3])

            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> int:
                try:
                    return next(self._iterator)
                except StopIteration:
                    raise StopAsyncIteration from None

        assert await collect(zip_longest(AIter(), ["a"], fillvalue="?")) == [
            (1, "a"),
            (2, "?"),
            (3, "?"),
        ]

    async def test_all_empty_iterables(self) -> None:
        assert await collect(zip_longest([], ())) == []

    async def test_no_iterables(self) -> None:
        assert await collect(zip_longest()) == []

    async def test_checkpoints_all_empty_iterables(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(zip_longest([], ()))

    async def test_checkpoints_no_iterables(self) -> None:
        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await anext(zip_longest())
