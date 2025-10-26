from __future__ import annotations

import asyncio

import pytest

from anyio import (
    Semaphore,
)
from anyio._core._streams import create_memory_object_stream
from anyio._core._tasks import create_bounded_task_group
from anyio.abc import CapacityLimiter
from anyio.streams.memory import MemoryObjectSendStream

from .conftest import asyncio_params


class TestSemaphoreInBoundedGroup:
    async def test_contextmanager(self) -> None:
        async def acquire() -> None:
            assert semaphore.value in (0, 1)

        semaphore = Semaphore(2)
        async with create_bounded_task_group(semaphore) as tg:
            tg.start_soon(acquire, name="task 1")
            tg.start_soon(acquire, name="task 2")

        assert semaphore.value == 2

    async def test_fast_acquire(self) -> None:
        other_task_called = False

        async def other_task() -> None:
            nonlocal other_task_called
            other_task_called = True

        semaphore = Semaphore(1, fast_acquire=True)
        async with create_bounded_task_group(semaphore) as tg:
            tg.start_soon(other_task)
            async with semaphore:
                assert not other_task_called

    @pytest.mark.parametrize("anyio_backend", asyncio_params)
    async def test_asyncio_deadlock(self) -> None:
        semaphore = Semaphore(1)

        async def acquire() -> None:
            await asyncio.sleep(0)

        async with create_bounded_task_group(semaphore) as tg:
            await tg.start(acquire)
            await tg.start(acquire)

        assert semaphore.value == 1

    @pytest.mark.parametrize("anyio_backend", asyncio_params)
    async def test_send_stream(self) -> None:
        limiter = Semaphore(1)
        send_stream, receive_stream = create_memory_object_stream()

        async def acquire(
            send_stream_: MemoryObjectSendStream[int], task_num: int
        ) -> None:
            await send_stream_.send(task_num)

        results = []
        async with create_bounded_task_group(limiter) as tg:
            async with send_stream:
                tg.start_soon(acquire, send_stream, 1)
                tg.start_soon(acquire, send_stream, 2)
                tg.start_soon(acquire, send_stream, 3)

                async with receive_stream:
                    async for result in receive_stream:
                        results.append(result)

                        if len(results) >= 3:
                            tg.cancel_scope.cancel()
        assert results == [1, 2, 3]
        assert limiter.value == 1


class TestCapacityLimiterInBoundedGroup:
    async def test_contextmanager(self) -> None:
        async def acquire() -> None:
            assert limiter.available_tokens in (0, 1)

        limiter = CapacityLimiter(2)
        async with create_bounded_task_group(limiter) as tg:
            tg.start_soon(acquire, name="task 1")
            tg.start_soon(acquire, name="task 2")
            tg.start_soon(acquire, name="task 3")

        assert limiter.available_tokens == 2

    @pytest.mark.parametrize("anyio_backend", asyncio_params)
    async def test_asyncio_deadlock(self) -> None:
        limiter = CapacityLimiter(1)

        async def acquire() -> None:
            return await asyncio.sleep(0)

        async with create_bounded_task_group(limiter) as tg:
            await tg.start(acquire)
            await tg.start(acquire)

        assert limiter.available_tokens == 1

    @pytest.mark.parametrize("anyio_backend", asyncio_params)
    async def test_send_stream(self) -> None:
        limiter = CapacityLimiter(1)
        send_stream, receive_stream = create_memory_object_stream()

        async def acquire(
            send_stream_: MemoryObjectSendStream[int], task_num: int
        ) -> None:
            await send_stream_.send(task_num)

        results = []
        async with create_bounded_task_group(limiter) as tg:
            async with send_stream:
                tg.start_soon(acquire, send_stream, 1)
                tg.start_soon(acquire, send_stream, 2)
                tg.start_soon(acquire, send_stream, 3)

                async with receive_stream:
                    async for result in receive_stream:
                        results.append(result)

                        if len(results) >= 3:
                            tg.cancel_scope.cancel()
        assert results == [1, 2, 3]
        assert limiter.available_tokens == 1
