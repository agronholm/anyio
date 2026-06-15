from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable
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
    awaitable1: Awaitable[R],
    awaitable2: Awaitable[S],
    /,
) -> tuple[R, S]: ...


@overload
async def gather(
    awaitable1: Awaitable[R],
    awaitable2: Awaitable[S],
    awaitable3: Awaitable[T],
    /,
) -> tuple[R, S, T]: ...


@overload
async def gather(
    awaitable1: Awaitable[R],
    awaitable2: Awaitable[S],
    awaitable3: Awaitable[T],
    awaitable4: Awaitable[U],
    /,
) -> tuple[R, S, T, U]: ...


@overload
async def gather(
    awaitable1: Awaitable[R],
    awaitable2: Awaitable[S],
    awaitable3: Awaitable[T],
    awaitable4: Awaitable[U],
    awaitable5: Awaitable[V],
    /,
) -> tuple[R, S, T, U, V]: ...


@overload
async def gather(
    awaitable1: Awaitable[R],
    awaitable2: Awaitable[S],
    awaitable3: Awaitable[T],
    awaitable4: Awaitable[U],
    awaitable5: Awaitable[V],
    awaitable6: Awaitable[W],
    /,
) -> tuple[R, S, T, U, V, W]: ...


# handle arbitrary length if awaitables are all of the same type
@overload
async def gather(*awaitables: Awaitable[R]) -> tuple[R, ...]: ...


async def gather(*awaitables: Awaitable[Any]) -> tuple[Any, ...]:
    """
    Run awaitable objects concurrently in a task group. The order of result values
    corresponds to the order of awaitables passed.
    """
    if not awaitables:
        return ()
    results: list[TaskHandle[Any, Any]] = []

    async with create_task_group() as tg:
        for awaitable in awaitables:
            results.append(tg.create_task(awaitable))  # type: ignore

    return tuple(r.return_value for r in results)


@asynccontextmanager
async def as_completed(
    *awaitables: Awaitable[R],
) -> AsyncGenerator[MemoryObjectReceiveStream[R]]:
    """
    Run awaitable objects concurrently in a task group, returning an iterator which can
    be used to get result values as they resolve in the order they finish.
    """
    send, recv = create_memory_object_stream[R]()

    async def runner(awaitable: Awaitable[R], _send: MemoryObjectSendStream[R]) -> None:
        async with _send:
            await _send.send(await awaitable)

    async with recv, create_task_group() as tg:
        async with send:
            for awaitable in awaitables:
                tg.start_soon(runner, awaitable, send.clone())
        try:
            yield recv
        finally:
            tg.cancel_scope.cancel()
