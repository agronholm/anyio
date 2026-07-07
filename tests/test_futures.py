from __future__ import annotations

from typing import Any

import pytest

from anyio import (
    Future,
    FutureAlreadyFinished,
    FutureCancelled,
    TaskCancelled,
    TaskFailed,
    TaskNotFinished,
    create_task_group,
)
from anyio.lowlevel import (
    # cancel_shielded_checkpoint,
    checkpoint,
    # checkpoint_if_cancelled,
)


class TestFuture:
    async def test_result(self) -> None:
        future: Future[int] = Future()
        future.set_result(1)

        result = await future
        assert result == 1

    async def test_disallowing_multiple_results(self) -> None:
        future: Future[int] = Future()
        future.set_result(1)

        with pytest.raises(FutureAlreadyFinished, match="future has already finished"):
            future.set_result(0)

    async def test_waiting_for_result(self) -> None:
        async def task(fut: Future[int], value: int) -> None:
            await checkpoint()
            fut.set_result(value)

        future: Future[int] = Future()
        async with create_task_group() as tg:
            tg.start_soon(task, future, 2)
            assert (await future) == 2

    async def test_waiting_with_wait(self) -> None:
        async def task(fut: Future[int], value: int) -> None:
            await checkpoint()
            fut.set_result(value)

        future: Future[int] = Future()
        async with create_task_group() as tg:
            tg.start_soon(task, future, 2)
            await future.wait()
            assert future.return_value == 2

    async def test_raising_exception(self) -> None:
        async def task(fut: Future[int]) -> None:
            await checkpoint()
            fut.set_exception(RuntimeError("testing runtime error"))

        future: Future[int] = Future()
        async with create_task_group() as tg:
            tg.start_soon(task, future)
            with pytest.raises(TaskFailed, match="the future raised an exception"):
                await future

    async def test_already_cancelled(self) -> None:
        future: Future[int] = Future()
        future.cancel()
        with pytest.raises(FutureCancelled, match=r"future was cancelled"):
            future.set_result(1)

    async def test_cancelled_wait(self) -> None:
        future: Future[int] = Future()
        future.cancel()
        with pytest.raises(FutureCancelled, match=r"future was cancelled"):
            await future

    async def test_future_not_finished(self) -> None:
        future: Future[int] = Future()
        with pytest.raises(TaskNotFinished, match=r"the future has not finished yet"):
            _ = future.return_value

        with pytest.raises(TaskNotFinished, match=r"the future has not finished yet"):
            _ = future.exception

    async def test_future_cancelling_already_set_result(self) -> None:
        fut: Future[str] = Future()
        fut.set_result("Item")
        fut.cancel()
        assert await fut == "Item"

    async def test_future_cancelling_already_set_exception(self) -> None:
        fut: Future[Any] = Future()
        fut.set_exception(RuntimeError("Failed"))
        fut.cancel()
        with pytest.raises(TaskFailed, match=r"future raised an exception"):
            await fut

    async def test_future_cancelling_with_result(self) -> None:
        fut: Future[str] = Future()
        fut.cancel()

        with pytest.raises(FutureCancelled, match=r"future was cancelled"):
            fut.set_result("Item")

    async def test_future_cancelling_with_await(self) -> None:
        fut: Future[str] = Future()
        fut.cancel()

        with pytest.raises(FutureCancelled, match=r"future was cancelled"):
            await fut

    async def test_future_with_repr(self) -> None:
        repr_str = repr(Future(name="name"))
        assert repr_str == "<Future pending name='name'>"

    async def test_future_with_multiple_waiters(self) -> None:
        async with create_task_group() as tg:
            f = Future[str]()

            async def task() -> str:
                return await f

            tasks = (tg.start_soon(task), tg.start_soon(task))
            tg.cancel_scope.deadline += 2.0
            f.set_result("Finished")
            assert [await t for t in tasks] == ["Finished" for _ in tasks]

    async def test_cancelled_waiter_allows_other(self) -> None:
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

            f.set_result("Finished")

            tg.cancel_scope.deadline += 1.0
            assert await th2 == "Finished"
