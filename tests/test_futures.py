from __future__ import annotations

from typing import Any

import pytest

from anyio import (
    Future,
    FutureAlreadyFinished,
    FutureCancelled,
    FutureFailed,
    FutureNotFinished,
    TaskCancelled,
    create_task_group,
)
from anyio.lowlevel import checkpoint


async def test_result() -> None:
    future: Future[int] = Future()
    future.return_value = 1

    result = await future
    assert result == 1


async def test_disallowing_multiple_results() -> None:
    future: Future[int] = Future()
    future.return_value = 1

    with pytest.raises(FutureAlreadyFinished, match="future has already finished"):
        future.return_value = 0


async def test_waiting_for_result() -> None:
    async def task(fut: Future[int], value: int) -> None:
        await checkpoint()
        fut.return_value = value

    future: Future[int] = Future()
    async with create_task_group() as tg:
        tg.start_soon(task, future, 2)
        assert (await future) == 2


async def test_waiting_with_wait() -> None:
    async def task(fut: Future[int], value: int) -> None:
        await checkpoint()
        fut.return_value = value

    future: Future[int] = Future()
    async with create_task_group() as tg:
        tg.start_soon(task, future, 2)
        await future.wait()
        assert future.return_value == 2


async def test_raising_exception() -> None:
    async def task(fut: Future[int]) -> None:
        await checkpoint()
        fut.exception = RuntimeError("testing runtime error")

    future: Future[int] = Future()
    async with create_task_group() as tg:
        tg.start_soon(task, future)
        with pytest.raises(FutureFailed, match="the future raised an exception"):
            await future


async def test_already_cancelled() -> None:
    future: Future[int] = Future()
    future.cancel()
    with pytest.raises(FutureCancelled, match=r"future was cancelled"):
        future.return_value = 1


async def test_cancelled_wait() -> None:
    future: Future[int] = Future()
    future.cancel()
    with pytest.raises(FutureCancelled, match=r"future was cancelled"):
        await future


async def test_return_value_when_future_not_finished() -> None:
    future: Future[int] = Future()
    with pytest.raises(FutureNotFinished, match=r"the future has not finished yet"):
        _ = future.return_value


async def test_exception_when_future_not_finished() -> None:
    future: Future[int] = Future()
    with pytest.raises(FutureNotFinished, match=r"the future has not finished yet"):
        _ = future.exception


async def test_exception_when_future_failed() -> None:
    future: Future[int] = Future()
    exc = RuntimeError("foo")
    future.exception = exc
    assert future.exception is exc


async def test_exception_when_future_cancelled() -> None:
    future: Future[int] = Future()
    future.cancel()
    with pytest.raises(FutureCancelled, match=r"the future was cancelled"):
        _ = future.exception


async def test_cancelling_already_set_return_value() -> None:
    fut: Future[str] = Future()
    fut.return_value = "Item"
    fut.cancel()
    assert await fut == "Item"


async def test_cancelling_already_set_exception() -> None:
    fut: Future[Any] = Future()
    fut.exception = RuntimeError("Failed")
    fut.cancel()
    with pytest.raises(FutureFailed, match=r"future raised an exception"):
        await fut


async def test_cancelling_with_result() -> None:
    fut: Future[str] = Future()
    fut.cancel()

    with pytest.raises(FutureCancelled, match=r"future was cancelled"):
        fut.return_value = "Item"


async def test_repr() -> None:
    repr_str = repr(Future(name="name"))
    assert repr_str == "<Future pending name='name'>"


async def test_multiple_waiters() -> None:
    async with create_task_group() as tg:
        f = Future[str]()

        async def task() -> str:
            return await f

        tasks = (tg.start_soon(task), tg.start_soon(task))
        tg.cancel_scope.deadline += 2.0
        f.return_value = "Finished"
        assert [await t for t in tasks] == ["Finished" for _ in tasks]


async def test_cancelled_waiter_allows_other() -> None:
    async with create_task_group() as tg:
        f = Future[str]()

        async def task() -> str:
            return await f

        th1 = tg.start_soon(task)
        th2 = tg.start_soon(task)
        await checkpoint()

        th1.cancel()
        with pytest.raises(TaskCancelled):
            await th1

        f.return_value = "Finished"
        tg.cancel_scope.deadline += 1.0
        assert await th2 == "Finished"
