from __future__ import annotations

import gc
import sys
from collections.abc import AsyncIterator
from decimal import Decimal
from typing import Any, NoReturn
from weakref import ref

import pytest

from anyio import (
    CancelScope,
    Event,
    create_task_group,
    fail_after,
    get_cancelled_exc_class,
    move_on_after,
    run,
    sleep,
    wait_all_tasks_blocked,
)
from anyio.from_thread import start_blocking_portal
from anyio.functools import (
    AsyncCacheInfo,
    AsyncLRUCacheWrapper,
    _LRUMethodWrapper,
    cache,
    lru_cache,
    reduce,
)
from anyio.lowlevel import checkpoint

if sys.version_info >= (3, 11):
    from typing import assert_type
else:
    from typing_extensions import assert_type


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
    @pytest.mark.parametrize("maxsize", [1, 2, 3])
    @pytest.mark.parametrize("always_checkpoint", [False, True])
    def test_capacity_is_local_to_each_event_loop(
        self,
        anyio_backend_name: str,
        anyio_backend_options: dict[str, Any],
        maxsize: int,
        always_checkpoint: bool,
    ) -> None:
        calls = 0

        @lru_cache(maxsize=maxsize, always_checkpoint=always_checkpoint)
        async def func(key: int) -> int:
            nonlocal calls
            calls += 1
            return key

        async def exercise() -> None:
            previous_calls = calls
            for key in range(maxsize):
                assert await func(key) == key

            for key in range(maxsize):
                assert await func(key) == key

            assert calls - previous_calls == maxsize

        for _ in range(3):
            run(
                exercise,
                backend=anyio_backend_name,
                backend_options=anyio_backend_options,
            )

    @pytest.mark.parametrize("maxsize", [0, 2, None])
    def test_statistics_are_local_to_each_event_loop(
        self,
        anyio_backend_name: str,
        anyio_backend_options: dict[str, Any],
        maxsize: int | None,
    ) -> None:
        @lru_cache(maxsize=maxsize)
        async def func(key: int) -> int:
            return key

        empty_info = AsyncCacheInfo(0, 0, maxsize, 0, None)
        filled_info = AsyncCacheInfo(
            0 if maxsize == 0 else 1,
            2 if maxsize == 0 else 1,
            maxsize,
            0 if maxsize == 0 else 1,
            None,
        )

        async def exercise() -> None:
            assert func.cache_info() == empty_info
            assert await func(1) == 1
            assert await func(1) == 1
            assert func.cache_info() == filled_info

        assert func.cache_info() == empty_info
        for _ in range(3):
            run(
                exercise,
                backend=anyio_backend_name,
                backend_options=anyio_backend_options,
            )
            assert func.cache_info() == filled_info

    def test_statistics_do_not_retain_values_after_event_loop_finishes(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        class Value:
            pass

        @lru_cache(maxsize=2)
        async def func() -> Value:
            return Value()

        async def exercise() -> ref[Value]:
            value = await func()
            assert await func() is value
            return ref(value)

        value_ref = run(
            exercise,
            backend=anyio_backend_name,
            backend_options=anyio_backend_options,
        )
        # Weak-reference callbacks release the loop-local cache in stages on PyPy.
        # Allow subsequent collections to reclaim values released by those callbacks.
        for _ in range(10):
            gc.collect()
            if value_ref() is None:
                break

        assert value_ref() is None
        assert func.cache_info() == AsyncCacheInfo(1, 1, 2, 1, None)

    def test_cache_clear_does_not_affect_other_event_loops(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        @lru_cache(maxsize=2)
        async def func(key: int) -> int:
            return key

        async def info() -> AsyncCacheInfo:
            return func.cache_info()

        async def clear() -> None:
            func.cache_clear()

        with (
            start_blocking_portal(
                backend=anyio_backend_name, backend_options=anyio_backend_options
            ) as first,
            start_blocking_portal(
                backend=anyio_backend_name, backend_options=anyio_backend_options
            ) as second,
        ):
            for portal in (first, second):
                for key in (1, 2, 1):
                    assert portal.call(func, key) == key

                assert portal.call(info) == AsyncCacheInfo(1, 2, 2, 2, None)

            first.call(clear)
            assert first.call(info) == AsyncCacheInfo(0, 0, 2, 0, None)
            assert second.call(info) == AsyncCacheInfo(1, 2, 2, 2, None)
            assert second.call(func, 2) == 2
            assert second.call(info) == AsyncCacheInfo(2, 2, 2, 2, None)

    async def test_cache_clear_isolates_in_flight_statistics(self) -> None:
        calls = 0
        ready = Event()
        results: list[int] = []

        @lru_cache(maxsize=2)
        async def func() -> int:
            nonlocal calls
            calls += 1
            result = calls
            if result == 1:
                await ready.wait()

            return result

        async def call() -> None:
            results.append(await func())

        async with create_task_group() as tg:
            tg.start_soon(call)
            tg.start_soon(call)
            await wait_all_tasks_blocked()
            func.cache_clear()
            assert await func() == 2
            ready.set()

        assert results == [1, 1]
        assert func.cache_info() == AsyncCacheInfo(0, 1, 2, 1, None)
        assert await func() == 2
        assert func.cache_info() == AsyncCacheInfo(1, 1, 2, 1, None)

    def test_bad_func_argument(self) -> None:
        with pytest.raises(TypeError, match="the first argument must be callable"):
            lru_cache(10)  # type: ignore[call-overload]

    def test_cache_parameters(self) -> None:
        @lru_cache(maxsize=10, typed=True, ttl=3)
        async def func(x: int) -> int:
            return x

        assert func.cache_parameters() == {
            "maxsize": 10,
            "typed": True,
            "always_checkpoint": False,
            "ttl": 3,
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
        assert statistics == AsyncCacheInfo(3, 2, 128, 2, None)
        assert statistics.hits == 3
        assert statistics.misses == 2
        assert statistics.maxsize == 128
        assert statistics.currsize == 2

        func.cache_clear()
        assert func.cache_info() == (0, 0, 128, 0, None)

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

    @staticmethod
    async def _do_cache_asserts(
        wrapper: _LRUMethodWrapper[int] | AsyncLRUCacheWrapper[..., int],
    ) -> None:
        assert wrapper.cache_parameters() == {
            "always_checkpoint": False,
            "maxsize": 128,
            "typed": False,
            "ttl": None,
        }
        statistics = wrapper.cache_info()
        assert statistics.hits == 2
        assert statistics.misses == 2

        wrapper.cache_clear()
        statistics = wrapper.cache_info()
        assert statistics.hits == 0
        assert statistics.misses == 0

    async def test_cached_static_method(self) -> None:
        class Foo:
            @staticmethod
            @lru_cache
            async def static_method(x: int) -> int:
                return x

        for _ in range(2):
            assert await Foo.static_method(1) == 1
            assert await Foo.static_method(2) == 2

        await self._do_cache_asserts(Foo.static_method)

    async def test_cached_class_method(self) -> None:
        class Foo:
            @classmethod
            @lru_cache
            async def cls_method(cls, x: int) -> int:
                return x

        for _ in range(2):
            assert await Foo.cls_method(1) == 1
            assert await Foo.cls_method(2) == 2

        await self._do_cache_asserts(Foo.cls_method)

    async def test_cached_instance_method(self) -> None:
        class Foo:
            @lru_cache
            async def instance_method(self, x: int) -> int:
                return x

        foo = Foo()
        for _ in range(2):
            assert await foo.instance_method(1) == 1
            assert await foo.instance_method(2) == 2

        await self._do_cache_asserts(Foo().instance_method)

    async def test_ttl_cache_hit(self) -> None:
        called = False

        @lru_cache(ttl=1)
        async def func() -> float:
            nonlocal called
            previous = called
            called = True
            await checkpoint()
            return previous

        assert not await func()
        # Should be a cache hit
        assert not await func()

        statistics = func.cache_info()
        assert statistics.hits == 1
        assert statistics.misses == 1
        assert statistics.currsize == 1
        assert statistics.ttl == 1

    async def test_ttl_expiration_evicts(self) -> None:
        called = False

        @lru_cache(ttl=1)
        async def func() -> bool:
            nonlocal called
            previous = called
            called = True
            await checkpoint()
            return previous

        # returns False
        assert not await func()
        # Should be a hit
        assert not await func()
        await sleep(1)
        # Should be a miss now
        assert await func()

        statistics = func.cache_info()
        assert statistics.hits == 1
        assert statistics.misses == 2
        assert statistics.currsize == 1
        assert statistics.ttl == 1

    @pytest.mark.parametrize("checkpoint", [False, True])
    async def test_ttl_contested_lock(self, checkpoint: bool) -> None:
        call_count = 0

        @lru_cache(ttl=1, always_checkpoint=checkpoint)
        async def sleeper(time: float) -> None:
            nonlocal call_count
            call_count += 1
            await sleep(time)

        async with create_task_group() as tg:
            for _ in range(100):
                tg.start_soon(sleeper, 0.1)

        assert call_count == 1

    @pytest.mark.parametrize("checkpoint", [False, True])
    async def test_ttl_sequential(self, checkpoint: bool) -> None:
        @lru_cache(ttl=1, always_checkpoint=checkpoint)
        async def sleeper(time: float) -> None:
            await sleep(time)

        with move_on_after(1) as scope:
            for _ in range(100):
                await sleeper(0.1)

        assert not scope.cancelled_caught

    async def test_type_overloads(self) -> None:
        @lru_cache(always_checkpoint=True)
        async def sleeper(time: float) -> None:
            pass

        @lru_cache
        async def foo() -> str:
            return "bar"

        assert_type(await sleeper(1), None)
        assert_type(await foo(), str)


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
