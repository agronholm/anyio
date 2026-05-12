from __future__ import annotations

import pytest

from anyio import (
    Future,
    FutureAlreadyFinished,
    FutureCancelled,
    # FutureNotFinished,
    # TaskCancelled,
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

    def test_disallowing_multiple_results(self) -> None:
        future: Future[int] = Future()
        future.set_result(1)

        with pytest.raises(FutureAlreadyFinished, match="future has already finished"):
            future.set_result(0)


    async def test_waiting_for_result(self) -> None:
        async def task(fut: Future[int], value: int):
            await checkpoint()
            fut.set_result(value)

        future: Future[int] = Future()
        async with create_task_group() as tg:
            tg.start_soon(task, future, 2)
            assert (await future) == 2

    async def test_waiting_with_wait(self) -> None:
        async def task(fut: Future[int], value: int):
            await checkpoint()
            fut.set_result(value)

        future: Future[int] = Future()
        async with create_task_group() as tg:
            tg.start_soon(task, future, 2)
            await future.wait()
            assert future.return_value == 2

    async def test_raising_exception(self) -> None:
        async def task(fut: Future[int]):
            await checkpoint()
            fut.set_exception(RuntimeError("testing runtime error"))

        future: Future[int] = Future()
        async with create_task_group() as tg:
            tg.start_soon(task, future, 2)
            with pytest.raises(RuntimeError, match=r"testing runtime error"):
                await future


    def test_already_cancelled(self) -> None:
        future: Future[int] = Future()
        future.cancel()
        with pytest.raises(FutureCancelled, match=r"future was cancelled"):
            future.set_result(1)

    async def test_cancelled_wait(self):
        future: Future[int] = Future()
        future.cancel()
        with pytest.raises(FutureCancelled, match=r"future was cancelled"):
            await future
