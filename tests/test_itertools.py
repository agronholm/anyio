from __future__ import annotations

from collections.abc import (
    AsyncGenerator,
    AsyncIterable,
    AsyncIterator,
    Iterable,
    Iterator,
)
from typing import Any, TypeVar, cast

import pytest

from anyio import CancelScope, create_task_group, get_cancelled_exc_class
from anyio.itertools import (
    accumulate,
    batched,
    chain,
    combinations,
    combinations_with_replacement,
    compress,
    count,
    cycle,
    dropwhile,
    filterfalse,
    groupby,
    islice,
    pairwise,
    permutations,
    product,
    repeat,
    starmap,
    takewhile,
    tee,
    zip_longest,
)
from anyio.lowlevel import (
    cancel_shielded_checkpoint,
    checkpoint,
    checkpoint_if_cancelled,
)

T = TypeVar("T")


async def collect(iterator: AsyncIterator[T]) -> list[T]:
    return [item async for item in iterator]


class AIter(AsyncIterator[T]):
    def __init__(self, iterable: Iterable[T]) -> None:
        self._iterator: Iterator[T] = iter(iterable)

    def __aiter__(self) -> AIter[T]:
        return self

    async def __anext__(self) -> T:
        await checkpoint_if_cancelled()
        try:
            value = next(self._iterator)
        except StopIteration:
            await cancel_shielded_checkpoint()
            raise StopAsyncIteration from None

        await cancel_shielded_checkpoint()
        return value


def aiter_from(iterable: Iterable[T]) -> AsyncIterator[T]:
    return AIter(iterable)


async def assert_cancelled_on_first_next(iterator: AsyncIterator[Any]) -> None:
    with CancelScope() as cs:
        cs.cancel()
        with pytest.raises(get_cancelled_exc_class()):
            await anext(iterator)


async def assert_checkpoints_on_first_next(iterator: AsyncIterator[Any]) -> None:
    finished = second_finished = False

    async def second_func() -> None:
        nonlocal second_finished
        assert not finished
        second_finished = True

    async with create_task_group() as tg:

        async def func() -> None:
            nonlocal finished
            tg.start_soon(second_func)
            with pytest.raises(StopAsyncIteration):
                await anext(iterator)

            finished = True

        tg.start_soon(func)

    assert finished
    assert second_finished


class TestAccumulate:
    async def test_iterable_variants(self) -> None:
        async def multiply(x: int, y: int) -> int:
            await checkpoint()
            return x * y

        cases = [
            (accumulate([1, 2, 3]), [1, 3, 6]),
            (accumulate([1, 2, 3], multiply), [1, 2, 6]),
            (accumulate([1, 2, 3], initial=10), [10, 11, 13, 16]),
            (accumulate([1, 2, 3], multiply, initial=2), [2, 2, 4, 12]),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_asynciter_variants(self) -> None:
        async def multiply(x: int, y: int) -> int:
            await checkpoint()
            return x * y

        cases = [
            (accumulate(aiter_from([1, 2, 3])), [1, 3, 6]),
            (accumulate(aiter_from([1, 2, 4]), multiply), [1, 2, 8]),
            (accumulate(aiter_from([1, 2, 3]), multiply, initial=2), [2, 2, 4, 12]),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_empty_inputs(self) -> None:
        iterator: AsyncIterator[int]
        for iterator in (accumulate([]), accumulate(aiter_from([]))):
            assert await collect(iterator) == []

    async def test_checkpoints_empty_inputs(self) -> None:
        iterator: AsyncIterator[int]
        for iterator in (accumulate([]), accumulate(aiter_from([]))):
            await assert_cancelled_on_first_next(iterator)

    async def test_checkpoints_initial_value(self) -> None:
        iterator: AsyncIterator[int]
        for iterator in (
            accumulate([], initial=1),
            accumulate(aiter_from([]), initial=1),
        ):
            await assert_cancelled_on_first_next(iterator)


class TestBatched:
    async def test_basic_cases(self) -> None:
        for iterator in (
            batched([1, 2, 3, 4, 5], 2),
            batched(aiter_from([1, 2, 3, 4, 5]), 2),
        ):
            assert await collect(iterator) == [(1, 2), (3, 4), (5,)]

    async def test_empty_inputs(self) -> None:
        iterator: AsyncIterator[tuple[int, ...]]
        for iterator in (batched([], 2), batched(aiter_from([]), 2)):
            assert await collect(iterator) == []

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

    async def test_checkpoints_empty_inputs(self) -> None:
        iterator: AsyncIterator[tuple[int, ...]]
        for iterator in (batched([], 2), batched(aiter_from([]), 2)):
            await assert_cancelled_on_first_next(iterator)


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

    async def test_checkpoints_empty_inputs(self) -> None:
        async def outer() -> AsyncIterator[Iterable[int] | AsyncIterable[int]]:
            yield []
            yield ()

        for iterator in (
            chain(),
            chain.from_iterable([]),
            chain.from_iterable(outer()),
        ):
            await assert_cancelled_on_first_next(iterator)


class TestCombinations:
    async def test_basic_cases(self) -> None:
        for iterator in (
            combinations([1, 2, 3], 2),
            combinations(aiter_from([1, 2, 3]), 2),
        ):
            assert await collect(iterator) == [(1, 2), (1, 3), (2, 3)]

    async def test_stepwise(self) -> None:
        iterator = combinations([0, 1, 2, 3], 3)
        assert await anext(iterator) == (0, 1, 2)
        assert await anext(iterator) == (0, 1, 3)
        assert await anext(iterator) == (0, 2, 3)
        assert await anext(iterator) == (1, 2, 3)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    async def test_edge_cases(self) -> None:
        cases = [
            (combinations([1, 2, 3], 0), [()]),
            (combinations([], 0), [()]),
            (combinations([1, 2], 3), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_negative_r(self) -> None:
        with pytest.raises(ValueError, match="r must be non-negative"):
            await anext(combinations([1, 2], -1))

    async def test_checkpoints_empty_result(self) -> None:
        await assert_cancelled_on_first_next(combinations([], 1))

    async def test_checkpoints_r_greater_than_pool(self) -> None:
        await assert_checkpoints_on_first_next(combinations([1, 2], 3))

    async def test_checkpoints_after_first_result(self) -> None:
        iterator = combinations([0, 1, 2], 2)
        assert await anext(iterator) == (0, 1)
        await assert_cancelled_on_first_next(iterator)


class TestCombinationsWithReplacement:
    async def test_basic_cases(self) -> None:
        expected = [(1, 1), (1, 2), (1, 3), (2, 2), (2, 3), (3, 3)]
        for iterator in (
            combinations_with_replacement([1, 2, 3], 2),
            combinations_with_replacement(aiter_from([1, 2, 3]), 2),
        ):
            assert await collect(iterator) == expected

    async def test_stepwise(self) -> None:
        iterator = combinations_with_replacement([0, 1, 2], 2)
        assert await anext(iterator) == (0, 0)
        assert await anext(iterator) == (0, 1)
        assert await anext(iterator) == (0, 2)
        assert await anext(iterator) == (1, 1)
        assert await anext(iterator) == (1, 2)
        assert await anext(iterator) == (2, 2)
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    async def test_edge_cases(self) -> None:
        r_greater_than_pool = [
            (1, 1, 1),
            (1, 1, 2),
            (1, 2, 2),
            (2, 2, 2),
        ]
        cases = [
            (combinations_with_replacement([1, 2, 3], 0), [()]),
            (combinations_with_replacement([], 0), [()]),
            (combinations_with_replacement(aiter_from([]), 0), [()]),
            (combinations_with_replacement([1, 2], 3), r_greater_than_pool),
            (combinations_with_replacement(aiter_from([]), 1), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_negative_r(self) -> None:
        with pytest.raises(ValueError, match="r must be non-negative"):
            await anext(combinations_with_replacement([1, 2], -1))

    async def test_checkpoints_empty_results(self) -> None:
        iterator: AsyncIterator[tuple[int, ...]]
        for iterator in (
            combinations_with_replacement([], 1),
            combinations_with_replacement(aiter_from([]), 1),
        ):
            await assert_cancelled_on_first_next(iterator)

    async def test_checkpoints_empty_result(self) -> None:
        await assert_checkpoints_on_first_next(combinations_with_replacement([], 1))

    async def test_checkpoints_after_first_result(self) -> None:
        iterator = combinations_with_replacement([0, 1, 2], 2)
        assert await anext(iterator) == (0, 0)
        await assert_cancelled_on_first_next(iterator)


class TestCompress:
    async def test_basic_cases(self) -> None:
        cases = [
            (compress("ABCDEF", [1, 0, 1, 0, 1, 1]), ["A", "C", "E", "F"]),
            (compress(aiter_from("ABCD"), [0, 1, 0, 1]), ["B", "D"]),
            (compress("ABCD", aiter_from([1, 0, 1, 1])), ["A", "C", "D"]),
            (compress("AB", [1, 0, 1, 1]), ["A"]),
            (compress("ABCD", [0, 0, 0, 0]), []),
            (compress([], [1, 0, 1]), []),
            (compress("ABCD", []), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_shorter_selectors(self) -> None:
        iterator = compress("ABCD", [1, 0])
        assert await anext(iterator) == "A"
        with pytest.raises(StopAsyncIteration):
            await anext(iterator)

    async def test_checkpoints_empty_result(self) -> None:
        await assert_cancelled_on_first_next(compress([], [1]))


class TestCount:
    async def test_defaults(self) -> None:
        iterator = cast(AsyncGenerator[int, None], count())
        try:
            assert await anext(iterator) == 0
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
        finally:
            await iterator.aclose()

    async def test_checkpoints(self) -> None:
        iterator = cast(AsyncGenerator[int, None], count())
        try:
            await assert_cancelled_on_first_next(iterator)
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
        iterator = cast(AsyncGenerator[int, None], cycle(aiter_from([1, 2])))
        try:
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
            assert await anext(iterator) == 1
            assert await anext(iterator) == 2
            assert await anext(iterator) == 1
        finally:
            await iterator.aclose()

    async def test_empty_inputs(self) -> None:
        iterator: AsyncIterator[int]
        for iterator in (cycle([]), cycle(aiter_from([]))):
            assert await collect(iterator) == []

    async def test_checkpoints_empty_inputs(self) -> None:
        iterator: AsyncIterator[int]
        for iterator in (cycle([]), cycle(aiter_from([]))):
            await assert_cancelled_on_first_next(iterator)

    async def test_checkpoints_replay(self) -> None:
        iterator = cast(AsyncGenerator[int, None], cycle([1]))
        try:
            assert await anext(iterator) == 1
            await assert_cancelled_on_first_next(iterator)
        finally:
            await iterator.aclose()


class TestDropwhile:
    async def test_basic_cases(self) -> None:
        async def less_than_three(value: int) -> bool:
            await checkpoint()
            return value < 3

        for iterator in (
            dropwhile(less_than_three, [1, 2, 3, 4]),
            dropwhile(less_than_three, aiter_from([1, 2, 3, 4])),
        ):
            assert await collect(iterator) == [3, 4]

    async def test_edge_cases(self) -> None:
        async def less_than_zero(value: int) -> bool:
            await checkpoint()
            return value < 0

        async def less_than_four(value: int) -> bool:
            await checkpoint()
            return value < 4

        cases = [
            (dropwhile(less_than_zero, [1, 2, 3]), [1, 2, 3]),
            (dropwhile(less_than_four, [1, 2, 3]), []),
            (dropwhile(less_than_zero, []), []),
            (dropwhile(less_than_zero, aiter_from([])), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_checkpoints_empty_results(self) -> None:
        async def less_than_zero(value: int) -> bool:
            await checkpoint()
            return value < 0

        async def less_than_four(value: int) -> bool:
            await checkpoint()
            return value < 4

        for iterator in (
            dropwhile(less_than_zero, []),
            dropwhile(less_than_four, [1, 2, 3]),
        ):
            await assert_cancelled_on_first_next(iterator)


class TestFilterfalse:
    async def test_basic_cases(self) -> None:
        async def is_even(value: int) -> bool:
            await checkpoint()
            return value % 2 == 0

        for iterator in (
            filterfalse(is_even, [1, 2, 3, 4]),
            filterfalse(is_even, aiter_from([1, 2, 3, 4])),
        ):
            assert await collect(iterator) == [1, 3]

    async def test_edge_cases(self) -> None:
        async def always_false(value: int) -> bool:
            await checkpoint()
            return False

        async def always_true(value: int) -> bool:
            await checkpoint()
            return True

        cases = [
            (filterfalse(always_false, [1, 2, 3]), [1, 2, 3]),
            (filterfalse(always_true, [1, 2, 3]), []),
            (filterfalse(always_false, []), []),
            (filterfalse(always_false, aiter_from([])), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_checkpoints_empty_results(self) -> None:
        async def always_false(value: int) -> bool:
            await checkpoint()
            return False

        async def always_true(value: int) -> bool:
            await checkpoint()
            return True

        for iterator in (
            filterfalse(always_false, []),
            filterfalse(always_true, [1, 2, 3]),
        ):
            await assert_cancelled_on_first_next(iterator)


class TestGroupby:
    async def test_basic_cases(self) -> None:
        async def parity(value: int) -> int:
            await checkpoint()
            return value % 2

        plain_expected = [(1, [1, 1]), (2, [2, 2]), (1, [1])]
        keyed_expected = [(1, [1, 3]), (0, [2, 4]), (1, [5, 7])]

        cases = [
            (groupby([1, 1, 2, 2, 1]), plain_expected),
            (groupby([1, 3, 2, 4, 5, 7], parity), keyed_expected),
            (groupby(aiter_from([1, 1, 2, 2, 1])), plain_expected),
            (groupby(aiter_from([1, 3, 2, 4, 5, 7]), parity), keyed_expected),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_empty_inputs(self) -> None:
        iterator: AsyncIterator[tuple[int, list[int]]]
        for iterator in (groupby([]), groupby(aiter_from([]))):
            assert await collect(iterator) == []

    async def test_checkpoints_empty_inputs(self) -> None:
        iterator: AsyncIterator[tuple[int, list[int]]]
        for iterator in (groupby([]), groupby(aiter_from([]))):
            await assert_cancelled_on_first_next(iterator)


class TestIslice:
    async def test_basic_slices(self) -> None:
        cases = [
            (islice([0, 1, 2, 3, 4], 3), [0, 1, 2]),
            (islice([0, 1, 2, 3, 4], None, 3), [0, 1, 2]),
            (islice([0, 1, 2, 3, 4], 1, 4), [1, 2, 3]),
            (islice([0, 1, 2, 3, 4, 5], 1, 6, 2), [1, 3, 5]),
            (islice([0, 1, 2, 3, 4], 1, None, 2), [1, 3]),
            (islice([0, 1, 2, 3, 4], 1, 4, None), [1, 2, 3]),
            (islice([], 3), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

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
        assert await collect(islice(aiter_from([0, 1, 2, 3, 4]), 1, 4)) == [1, 2, 3]

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

    async def test_checkpoints_empty_results(self) -> None:
        for iterator in (islice([1, 2, 3], 0), islice([], 3)):
            await assert_cancelled_on_first_next(iterator)


class TestPairwise:
    async def test_basic_cases(self) -> None:
        for iterator in (pairwise([1, 2, 3, 4]), pairwise(aiter_from([1, 2, 3, 4]))):
            assert await collect(iterator) == [(1, 2), (2, 3), (3, 4)]

    async def test_empty_results(self) -> None:
        for iterator in (
            pairwise([]),
            pairwise([1]),
            pairwise(aiter_from([])),
            pairwise(aiter_from([1])),
        ):
            assert await collect(iterator) == []

    async def test_checkpoints_empty_results(self) -> None:
        for iterator in (
            pairwise([]),
            pairwise([1]),
            pairwise(aiter_from([])),
            pairwise(aiter_from([1])),
        ):
            await assert_cancelled_on_first_next(iterator)


class TestPermutations:
    async def test_basic_cases(self) -> None:
        cases = [
            (
                permutations("ABCD", 2),
                [
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
                ],
            ),
            (
                permutations(range(3)),
                [
                    (0, 1, 2),
                    (0, 2, 1),
                    (1, 0, 2),
                    (1, 2, 0),
                    (2, 0, 1),
                    (2, 1, 0),
                ],
            ),
            (
                permutations(aiter_from([0, 1, 2]), 2),
                [(0, 1), (0, 2), (1, 0), (1, 2), (2, 0), (2, 1)],
            ),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_edge_cases(self) -> None:
        for iterator, expected in (
            (permutations("AB", 0), [()]),
            (permutations("AB", 3), []),
        ):
            assert await collect(iterator) == expected

    async def test_negative_r(self) -> None:
        with pytest.raises(ValueError, match="r must be non-negative"):
            await anext(permutations("AB", -1))

    async def test_invalid_r_type(self) -> None:
        permutations_any = cast(Any, permutations)
        with pytest.raises(TypeError, match="Expected int as r"):
            await anext(permutations_any("AB", "a"))

    async def test_checkpoints_empty_result(self) -> None:
        await assert_cancelled_on_first_next(permutations("AB", 3))

    async def test_checkpoints_r_greater_than_pool(self) -> None:
        await assert_checkpoints_on_first_next(permutations("AB", 3))

    async def test_checkpoints_after_first_result(self) -> None:
        iterator = permutations("ABC", 2)
        assert await anext(iterator) == ("A", "B")
        await assert_cancelled_on_first_next(iterator)

    async def test_custom_start_and_step(self) -> None:
        iterator = cast(AsyncGenerator[int, None], count(10, -3))
        try:
            assert await anext(iterator) == 10
            assert await anext(iterator) == 7
            assert await anext(iterator) == 4
        finally:
            await iterator.aclose()


class TestProduct:
    async def test_basic_cases(self) -> None:
        cases = [
            (product("AB", "xy"), [("A", "x"), ("A", "y"), ("B", "x"), ("B", "y")]),
            (
                product(range(2), repeat=3),
                [
                    (0, 0, 0),
                    (0, 0, 1),
                    (0, 1, 0),
                    (0, 1, 1),
                    (1, 0, 0),
                    (1, 0, 1),
                    (1, 1, 0),
                    (1, 1, 1),
                ],
            ),
            (
                product(aiter_from([0, 1]), "ab"),
                [(0, "a"), (0, "b"), (1, "a"), (1, "b")],
            ),
            (product(), [()]),
            (product("AB", repeat=0), [()]),
            (product([], "ab"), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_negative_repeat(self) -> None:
        with pytest.raises(ValueError, match="repeat argument cannot be negative"):
            await anext(product("AB", repeat=-1))

    async def test_invalid_repeat_type(self) -> None:
        product_any = cast(Any, product)
        with pytest.raises(TypeError, match="cannot be interpreted as an integer"):
            await anext(product_any("AB", repeat="a"))

    async def test_checkpoints_empty_result(self) -> None:
        await assert_cancelled_on_first_next(product([], "ab"))

    async def test_checkpoints_empty_result_non_cancelled(self) -> None:
        await assert_checkpoints_on_first_next(product([], "ab"))

    async def test_checkpoints_after_first_result(self) -> None:
        iterator = product("AB", "xy")
        assert await anext(iterator) == ("A", "x")
        await assert_cancelled_on_first_next(iterator)


class TestRepeat:
    async def test_infinite(self) -> None:
        iterator = cast(AsyncGenerator[str, None], repeat("x"))
        try:
            assert await anext(iterator) == "x"
            assert await anext(iterator) == "x"
            assert await anext(iterator) == "x"
        finally:
            await iterator.aclose()

    async def test_checkpoints(self) -> None:
        iterator = cast(AsyncGenerator[str, None], repeat("x"))
        try:
            await assert_cancelled_on_first_next(iterator)
        finally:
            await iterator.aclose()

    async def test_finite_cases(self) -> None:
        class Indexable:
            def __index__(self) -> int:
                return 2

        repeat_any = cast(Any, repeat)
        cases = [
            (repeat("x", 3), ["x", "x", "x"]),
            (repeat("x", 0), []),
            (repeat("x", -1), []),
            (repeat_any("x", Indexable()), ["x", "x"]),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_invalid_times_type(self) -> None:
        repeat_any = cast(Any, repeat)
        with pytest.raises(TypeError, match="cannot be interpreted as an integer"):
            await anext(repeat_any("x", "a"))

    async def test_checkpoints_empty_results(self) -> None:
        for iterator in (repeat("x", 0), repeat("x", -1)):
            await assert_cancelled_on_first_next(iterator)


class TestStarmap:
    async def test_basic_cases(self) -> None:
        async def power(a: int, b: int) -> int:
            await checkpoint()
            return a**b

        async def add(a: int, b: int) -> int:
            await checkpoint()
            return a + b

        async def multiply(a: int, b: int) -> int:
            await checkpoint()
            return a * b

        async def outer() -> AsyncIterator[Iterable[object] | AsyncIterable[object]]:
            yield (1, 2)
            yield (3, 4)

        async def args_iterable(a: int, b: int) -> AsyncIterator[object]:
            yield a
            yield b

        cases = [
            (starmap(power, [(2, 5), (3, 2), (10, 3)]), [32, 9, 1000]),
            (starmap(add, outer()), [3, 7]),
            (starmap(multiply, [args_iterable(2, 5), args_iterable(3, 2)]), [10, 6]),
            (starmap(lambda: checkpoint(), []), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_checkpoints_empty_iterable(self) -> None:
        async def func() -> None:
            await checkpoint()

        await assert_cancelled_on_first_next(starmap(func, []))


class TestTakewhile:
    async def test_basic_cases(self) -> None:
        async def less_than_five(value: int) -> bool:
            await checkpoint()
            return value < 5

        async def less_than_three(value: int) -> bool:
            await checkpoint()
            return value < 3

        cases = [
            (takewhile(less_than_five, [1, 4, 6, 3, 8]), [1, 4]),
            (takewhile(less_than_three, aiter_from([1, 2, 3, 1])), [1, 2]),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_edge_cases(self) -> None:
        async def less_than_four(value: int) -> bool:
            await checkpoint()
            return value < 4

        async def less_than_zero(value: int) -> bool:
            await checkpoint()
            return value < 0

        cases = [
            (takewhile(less_than_four, [1, 2, 3]), [1, 2, 3]),
            (takewhile(less_than_zero, [1, 2, 3]), []),
            (takewhile(less_than_zero, []), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_consumes_first_failing_element(self) -> None:
        async def predicate(value: int) -> bool:
            await checkpoint()
            return value < 5

        iterator = iter([1, 4, 6, 3, 8])
        assert await collect(takewhile(predicate, iterator)) == [1, 4]
        assert next(iterator) == 3

    async def test_checkpoints_empty_results(self) -> None:
        async def less_than_zero(value: int) -> bool:
            await checkpoint()
            return value < 0

        for iterator in (
            takewhile(less_than_zero, []),
            takewhile(less_than_zero, [1, 2, 3]),
        ):
            await assert_cancelled_on_first_next(iterator)


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
        iterator1, iterator2 = tee(aiter_from([1, 2, 3]))
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
        await assert_cancelled_on_first_next(iterator)

    async def test_checkpoints_buffered_replay(self) -> None:
        iterator1, iterator2 = tee([1])
        assert await anext(iterator1) == 1
        await assert_cancelled_on_first_next(iterator2)


class TestZipLongest:
    async def test_basic_cases(self) -> None:
        cases = [
            (
                zip_longest("ABCD", "xy", fillvalue="-"),
                [("A", "x"), ("B", "y"), ("C", "-"), ("D", "-")],
            ),
            (zip_longest([1, 2], [10]), [(1, 10), (2, None)]),
            (
                zip_longest(aiter_from([1, 2, 3]), ["a"], fillvalue="?"),
                [(1, "a"), (2, "?"), (3, "?")],
            ),
            (zip_longest([], ()), []),
            (zip_longest(), []),
        ]
        for iterator, expected in cases:
            assert await collect(iterator) == expected

    async def test_checkpoints_empty_results(self) -> None:
        for iterator in (zip_longest([], ()), zip_longest()):
            await assert_cancelled_on_first_next(iterator)
