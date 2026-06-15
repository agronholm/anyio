from __future__ import annotations

from collections.abc import AsyncGenerator, Coroutine
from contextlib import asynccontextmanager
from typing import Any, TypeVar, overload

from anyio import create_task_group
from anyio._core._streams import create_memory_object_stream
from anyio._core._tasks import TaskHandle
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

R = TypeVar("R")
S = TypeVar("S")
T = TypeVar("T")
U = TypeVar("U")
V = TypeVar("V")
W = TypeVar("W")


@overload
async def gather(
    coro1: Coroutine[Any, Any, R], coro2: Coroutine[Any, Any, S], /
) -> tuple[R, S]: ...


@overload
async def gather(
    coro1: Coroutine[Any, Any, R],
    coro2: Coroutine[Any, Any, S],
    coro3: Coroutine[Any, Any, T],
    /,
) -> tuple[R, S, T]: ...


@overload
async def gather(
    coro1: Coroutine[Any, Any, R],
    coro2: Coroutine[Any, Any, S],
    coro3: Coroutine[Any, Any, T],
    coro4: Coroutine[Any, Any, U],
    /,
) -> tuple[R, S, T, U]: ...


@overload
async def gather(
    coro1: Coroutine[Any, Any, R],
    coro2: Coroutine[Any, Any, S],
    coro3: Coroutine[Any, Any, T],
    coro4: Coroutine[Any, Any, U],
    coro5: Coroutine[Any, Any, V],
    /,
) -> tuple[R, S, T, U, V]: ...


@overload
async def gather(
    coro1: Coroutine[Any, Any, R],
    coro2: Coroutine[Any, Any, S],
    coro3: Coroutine[Any, Any, T],
    coro4: Coroutine[Any, Any, U],
    coro5: Coroutine[Any, Any, V],
    coro6: Coroutine[Any, Any, W],
    /,
) -> tuple[R, S, T, U, V, W]: ...


# handle arbitrary length if awaitables are all of the same type
@overload
async def gather(*coros: Coroutine[Any, Any, R]) -> tuple[R, ...]: ...


async def gather(*coros: Coroutine[Any, Any, Any]) -> tuple[Any, ...]:
    """
    Run coroutines concurrently in a task group. The order of result values corresponds
    to the order of coroutines passed.
    """
    handles: list[TaskHandle[Any, Any]] = []

    async with create_task_group() as tg:
        handles.extend([tg.create_task(coro) for coro in coros])

    return tuple(r.return_value for r in handles)


@asynccontextmanager
async def as_completed(
    *coros: Coroutine[Any, Any, R],
) -> AsyncGenerator[MemoryObjectReceiveStream[R]]:
    """
    Run awaitable objects concurrently in a task group, returning an iterator which can
    be used to get result values as they resolve in the order they finish.
    """
    send, recv = create_memory_object_stream[R]()

    async def runner(
        coro: Coroutine[Any, Any, R], _send: MemoryObjectSendStream[R]
    ) -> None:
        async with _send:
            await _send.send(await coro)

    async with recv, create_task_group() as tg:
        async with send:
            for coro in coros:
                tg.start_soon(runner, coro, send.clone())
        try:
            yield recv
        finally:
            tg.cancel_scope.cancel()
