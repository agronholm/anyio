from __future__ import annotations

from collections.abc import Awaitable, Generator
from typing import TYPE_CHECKING, Any

import pytest

from anyio import Event, amap, as_completed, gather
from anyio.lowlevel import checkpoint

if TYPE_CHECKING:
    from anyio._core._tasks import TaskHandle


async def test_gather_results_in_order() -> None:
    # Chain events so the tasks complete in reverse order (3, 2, 1)
    events = [Event() for _ in range(3)]
    events[-1].set()

    async def return_when(value: int) -> int:
        await events[value - 1].wait()
        if value > 1:
            events[value - 2].set()

        return value

    results = await gather(return_when(1), return_when(2), return_when(3))
    assert results == (1, 2, 3)


async def test_gather_propagates_exception() -> None:
    async def fail() -> None:
        raise ValueError("boom")

    async def succeed() -> int:
        return 1

    with pytest.RaisesGroup(pytest.RaisesExc(ValueError, match="boom")):
        await gather(succeed(), fail())


async def test_as_completed_ordering() -> None:
    events = {value: Event() for value in (1, 2, 3)}
    # Chain completions to occur in the order 2 -> 3 -> 1
    triggers: dict[int, Event | None] = {2: events[3], 3: events[1], 1: None}
    events[2].set()

    async def return_when(value: int) -> int:
        await events[value].wait()
        if (trigger := triggers[value]) is not None:
            trigger.set()

        return value

    results: list[int] = []
    async with as_completed(return_when(1), return_when(2), return_when(3)) as stream:
        results.extend([r.return_value async for r in stream])

    assert results == [2, 3, 1]


async def test_as_completed_naming() -> None:
    class Testing(Awaitable[int]):
        async def get_answer(self) -> int:
            return 42

        def __await__(self) -> Generator[Any, Any, int]:
            return self.get_answer().__await__()

    results: list[TaskHandle[Any]] = []
    async with as_completed(checkpoint(), Testing()) as stream:
        results.extend([r async for r in stream])

    # anyio._core._concurrency_utils.as_completed.<locals>.runner
    # would be name of both if coroutine name didn't pass through
    assert results[0].name != results[1].name


async def test_as_completed_no_coroutines() -> None:
    with pytest.raises(ValueError, match="at least one awaitable"):
        async with as_completed():
            pass


async def test_as_completed_propagates_exception() -> None:
    async def fail() -> None:
        raise ValueError("boom")

    async def succeed() -> int:
        await Event().wait()
        return 1

    with pytest.RaisesGroup(pytest.RaisesExc(ValueError, match="boom")):
        async with as_completed(succeed(), fail()) as stream:
            async for _ in stream:
                pass


async def test_as_completed_early_exit() -> None:
    async def return_now() -> int:
        return 1

    async def never() -> int:
        await Event().wait()
        return 2

    # Exiting after the first result must cancel the unfinished task
    async with as_completed(return_now(), never()) as stream:
        assert (await anext(stream)).return_value == 1


async def test_map_results_ordering() -> None:
    # Chain events so the tasks complete in reverse order (3, 2, 1)
    events = [Event() for _ in range(3)]
    events[-1].set()

    async def double(value: int) -> int:
        await events[value - 1].wait()
        if value > 1:
            events[value - 2].set()

        return value * 2

    results = await amap(double, [1, 2, 3])
    assert results == [2, 4, 6]


async def test_map_empty_args() -> None:
    async def double(value: int) -> int:
        return value * 2

    assert await amap(double, []) == []


async def test_map_propagates_exception() -> None:
    async def fail(value: int) -> int:
        if value == 2:
            raise ValueError("boom")

        return value

    with pytest.RaisesGroup(pytest.RaisesExc(ValueError, match="boom")):
        await amap(fail, [1, 2, 3])
