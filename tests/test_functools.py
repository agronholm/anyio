from __future__ import annotations

from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, NoReturn

import pytest

from anyio import (
    CancelScope,
    Event,
    create_task_group,
    fail_after,
    get_cancelled_exc_class,
    wait_all_tasks_blocked,
)
from anyio.functools import cache, lru_cache, reduce
from anyio.lowlevel import checkpoint


class TestCache:
    def test_wrap_sync_callable(self) -> None:
        @cache
        def func(x: int) -> int:
            return x

        assert func(1) == 1
        assert func(1) == 1
        statistics = func.cache_info()
        assert statistics.hits == 1
        assert statistics.misses == 1
        assert statistics.maxsize is None
        assert statistics.currsize == 1

    async def test_wrap_async_callable(self) -> None:
        @cache
        async def func(x: int) -> int:
            await checkpoint()
            return x

        assert await func(1) == 1
        assert await func(1) == 1
        statistics = func.cache_info()
        assert statistics.hits == 1
        assert statistics.misses == 1
        assert statistics.maxsize is None
        assert statistics.currsize == 1


class TestAsyncLRUCache:
    def test_bad_func_argument(self) -> None:
        with pytest.raises(TypeError, match="the first argument must be callable"):
            lru_cache(10)  # type: ignore[call-overload]

    def test_cache_parameters(self) -> None:
        @lru_cache(maxsize=10, typed=True)
        async def func(x: int) -> int:
            return x

        assert func.cache_parameters() == {
            "maxsize": 10,
            "typed": True,
            "always_checkpoint": False,
        }

    def test_wrap_sync_callable(self) -> None:
        @lru_cache(maxsize=10, typed=True)
        def func(x: int) -> int:
            return x

        assert func(1) == 1
        assert func(1) == 1
        statistics = func.cache_info()
        assert statistics.hits == 1
        assert statistics.misses == 1
        assert statistics.maxsize == 10
        assert statistics.currsize == 1

    @pytest.mark.parametrize("maxsize", [-1, 0])
    async def test_no_caching(self, maxsize: int) -> None:
        @lru_cache(maxsize=maxsize)
        async def func(x: int) -> int:
            await checkpoint()
            return x

        assert await func(1) == 1
        assert await func(2) == 2

        statistics = func.cache_info()
        assert statistics.hits == 0
        assert statistics.misses == 2
        assert statistics.maxsize == 0
        assert statistics.currsize == 0

    async def test_cache_clear(self) -> None:
        @lru_cache
        async def func(x: int) -> int:
            await checkpoint()
            return x

        assert await func(1) == 1
        for _ in range(2):
            assert await func(1) == 1
            assert await func(2) == 2

        statistics = func.cache_info()
        assert statistics == (3, 2, 128, 2)
        assert statistics.hits == 3
        assert statistics.misses == 2
        assert statistics.maxsize == 128
        assert statistics.currsize == 2

        func.cache_clear()
        assert func.cache_info() == (0, 0, 128, 0)

    async def test_untyped_caching(self) -> None:
        @lru_cache
        async def func(x: int | str) -> int:
            await checkpoint()
            return int(x)

        for _ in range(2):
            assert await func(1) == 1
            assert await func("2") == 2

        statistics = func.cache_info()
        assert statistics.hits == 2
        assert statistics.misses == 2
        assert statistics.maxsize == 128
        assert statistics.currsize == 2

    @pytest.mark.parametrize(
        "typed, expected_entries",
        [pytest.param(True, 2, id="typed"), pytest.param(False, 1, id="untyped")],
    )
    async def test_caching(self, typed: bool, expected_entries: int) -> None:
        @lru_cache(typed=typed)
        async def func(x: float | Decimal, y: float | Decimal) -> int:
            await checkpoint()
            return int(x) * int(y)

        for _ in range(2):
            assert await func(3.0, y=4.0) == 12
            assert await func(Decimal("3.0"), y=Decimal("4.0")) == 12

        statistics = func.cache_info()
        assert statistics.hits == 4 - expected_entries
        assert statistics.misses == expected_entries
        assert statistics.maxsize == 128
        assert statistics.currsize == expected_entries

    async def test_lru_eviction(self) -> None:
        @lru_cache(maxsize=3)
        async def func(x: int) -> int:
            await checkpoint()
            return x

        # First, saturate the cache
        for i in range(3):
            await func(i)

        statistics = func.cache_info()
        assert statistics.hits == 0
        assert statistics.misses == 3
        assert statistics.currsize == 3

        # Calling it with 3 should cache that value and evict value 0
        await func(3)
        statistics = func.cache_info()
        assert statistics.hits == 0
        assert statistics.misses == 4
        assert statistics.currsize == 3

        # Calling with value 0 should cause a miss now, and evict value 1
        await func(0)
        statistics = func.cache_info()
        assert statistics.hits == 0
        assert statistics.misses == 5
        assert statistics.currsize == 3

        # Calling with values 0, 2 and 3 should yield hits
        for i in 0, 2, 3:
            await func(i)

        statistics = func.cache_info()
        assert statistics.hits == 3
        assert statistics.misses == 5

    async def test_concurrent_access(self) -> None:
        @lru_cache
        async def func(x: int) -> int:
            await event.wait()
            return x

        event = Event()
        async with create_task_group() as tg:
            tg.start_soon(func, 1)
            tg.start_soon(func, 1)
            await wait_all_tasks_blocked()
            event.set()

        statistics = func.cache_info()
        assert statistics.hits == 1
        assert statistics.misses == 1

    async def test_args_kwargs_cache_key(self) -> None:
        counter = 0

        @lru_cache
        async def func(*args: Any, **kwargs: Any) -> int:
            nonlocal counter
            await checkpoint()
            counter += 1
            return counter

        # These two calls should be cached with different keys
        assert await func(1, "y", 2) == 1
        assert await func(1, y=2) == 2

    async def test_cache_same_function_twice(self) -> None:
        counter = 0

        async def func() -> int:
            nonlocal counter
            await checkpoint()
            counter += 1
            return counter

        cached_1 = lru_cache()(func)
        cached_2 = lru_cache()(func)

        # This should yield two cache misses
        assert await cached_1() == 1
        assert await cached_2() == 2

    async def test_lock_granularity(self) -> None:
        """
        Test that calls to the cached function with different arguments can occur
        concurrently and do not wait for a shared lock.

        """

        @lru_cache
        async def func(set_event: bool) -> None:
            if set_event:
                event.set()
            else:
                await event.wait()

        event = Event()
        with fail_after(5):
            async with create_task_group() as tg:
                tg.start_soon(func, False)
                tg.start_soon(func, True)

    async def test_always_checkpoint(self) -> None:
        @lru_cache(always_checkpoint=True)
        async def func(x: int) -> int:
            return x

        # With always_checkpoint=1, calling the function in a cancelled cancel scope
        # when the cache has been filled will raise a cancellation exception due to the
        # forced checkpoint
        await func(1)
        with CancelScope() as scope, pytest.raises(get_cancelled_exc_class()):
            scope.cancel()
            await func(1)


class TestReduce:
    async def test_not_iterable(self) -> None:
        with pytest.raises(
            TypeError, match="argument 2 must be an iterable or async iterable"
        ):
            await reduce(lambda x, y: x + y, 1)  # type: ignore[call-overload]

    async def test_no_initial(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x + y

        assert await reduce(func, [1, 2, 3]) == 6

    async def test_has_initial(self) -> None:
        async def func(x: int, y: str) -> int:
            await checkpoint()
            return x + int(y)

        assert await reduce(func, ["1", "2", "3"], 2) == 8

    async def test_empty_iter_no_initial(self) -> None:
        with pytest.raises(
            TypeError, match=r"reduce\(\) of empty sequence with no initial value"
        ):
            await reduce(lambda x, y: x + y, [])

    async def test_asynciter_no_initial(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x + y

        async def asyncgen() -> AsyncIterator[int]:
            yield 1
            yield 2
            yield 3

        assert await reduce(func, asyncgen()) == 6

    async def test_asynciter_has_initial(self) -> None:
        async def func(x: int, y: str) -> int:
            await checkpoint()
            return x + int(y)

        async def asyncgen() -> AsyncIterator[str]:
            yield "1"
            yield "2"
            yield "3"

        assert await reduce(func, asyncgen(), 2) == 8

    async def test_empty_iterable_no_initial(self) -> None:
        with pytest.raises(
            TypeError, match=r"reduce\(\) of empty sequence with no initial value"
        ):
            await reduce(lambda x, y: x + y, ())

    async def test_empty_async_iterable_no_initial(self) -> None:
        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        with pytest.raises(
            TypeError, match=r"reduce\(\) of empty sequence with no initial value"
        ):
            await reduce(lambda x, y: x + y, AIter())

    async def test_checkpoints_empty_iterable(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x + y

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await reduce(func, [], 1)

    async def test_checkpoints_empty_async_iterable(self) -> None:
        async def func(x: int, y: int) -> int:
            await checkpoint()
            return x + y

        class AIter:
            def __aiter__(self) -> AIter:
                return self

            async def __anext__(self) -> NoReturn:
                raise StopAsyncIteration

        with CancelScope() as cs:
            cs.cancel()
            with pytest.raises(get_cancelled_exc_class()):
                await reduce(func, AIter(), 1)
