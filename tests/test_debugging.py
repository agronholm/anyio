from __future__ import annotations

import asyncio
from collections.abc import AsyncGenerator
from types import CoroutineType
from typing import TYPE_CHECKING, Any, cast

import pytest

import anyio
import anyio.lowlevel
from anyio import (
    Event,
    TaskInfo,
    create_task_group,
    get_current_task,
    get_running_tasks,
    move_on_after,
    wait_all_tasks_blocked,
)

from .conftest import asyncio_params

if TYPE_CHECKING:
    from anyio.abc import TaskStatus


def test_main_task_name(
    anyio_backend_name: str, anyio_backend_options: dict[str, Any]
) -> None:
    task_name = None

    async def main() -> None:
        nonlocal task_name
        task_name = get_current_task().name

    anyio.run(main, backend=anyio_backend_name, backend_options=anyio_backend_options)
    assert task_name == "tests.test_debugging.test_main_task_name.<locals>.main"

    # Work around sniffio/asyncio bug that leaves behind an unclosed event loop
    if anyio_backend_name == "asyncio":
        import asyncio
        import gc

        for loop in [
            obj
            for obj in gc.get_objects()
            if isinstance(obj, asyncio.AbstractEventLoop)
        ]:
            loop.close()


@pytest.mark.parametrize(
    "name_input,expected",
    [
        (None, "tests.test_debugging.test_non_main_task_name.<locals>.non_main"),
        (b"name", "b'name'"),
        ("name", "name"),
        ("", ""),
    ],
)
async def test_non_main_task_name(
    name_input: bytes | str | None, expected: str
) -> None:
    async def non_main(*, task_status: TaskStatus[str | None]) -> None:
        task_status.started(anyio.get_current_task().name)

    async with anyio.create_task_group() as tg:
        name = await tg.start(non_main, name=name_input)

    assert name == expected


async def test_get_running_tasks() -> None:
    async def inspect() -> None:
        await wait_all_tasks_blocked()
        new_tasks = set(get_running_tasks()) - existing_tasks
        task_infos[:] = sorted(new_tasks, key=lambda info: info.name or "")
        event.set()

    event = Event()
    task_infos: list[TaskInfo] = []
    host_task = get_current_task()
    async with create_task_group() as tg:
        existing_tasks = set(get_running_tasks())
        tg.start_soon(event.wait, name="task1")
        tg.start_soon(event.wait, name="task2")
        tg.start_soon(inspect)

    assert len(task_infos) == 3
    expected_names = [
        "task1",
        "task2",
        "tests.test_debugging.test_get_running_tasks.<locals>.inspect",
    ]
    for task, expected_name in zip(task_infos, expected_names, strict=True):
        assert task.parent_id == host_task.id
        assert task.name == expected_name
        assert repr(task).endswith(f"TaskInfo(id={task.id}, name={expected_name!r})")


@pytest.mark.parametrize("anyio_backend", asyncio_params)
async def test_wait_all_tasks_blocked_asend(anyio_backend: str) -> None:
    """Test that wait_all_tasks_blocked() does not crash on an `asend()` object."""

    async def agen_func() -> AsyncGenerator[None, None]:
        yield

    agen = agen_func()
    coro = agen.asend(None)
    loop = asyncio.get_running_loop()
    task = loop.create_task(cast("CoroutineType[Any, Any, Any]", coro))
    await wait_all_tasks_blocked()
    await task
    await agen.aclose()


async def test_wait_all_tasks_blocked_cancelled_task() -> None:
    done = False

    async def self_cancel(*, task_status: TaskStatus) -> None:
        nonlocal done
        task_status.started()
        with move_on_after(-1):
            await Event().wait()

        done = True

    async with create_task_group() as tg:
        await tg.start(self_cancel)
        await wait_all_tasks_blocked()
        assert done


class TestSequencer:
    async def test_order(self) -> None:
        sequencer = anyio.Sequencer()
        events: list[tuple[int, str]] = []

        async def worker(positions: tuple[int, int]) -> None:
            for position in positions:
                async with sequencer(position):
                    events.append((position, "enter"))
                    await anyio.lowlevel.checkpoint()
                    events.append((position, "exit"))

        async with create_task_group() as tg:
            tg.start_soon(worker, (2, 5))
            tg.start_soon(worker, (0, 3))
            tg.start_soon(worker, (1, 4))

        assert events == [
            (position, event) for position in range(6) for event in ("enter", "exit")
        ]

    async def test_reuse_completed_position(self) -> None:
        sequencer = anyio.Sequencer()
        async with sequencer(0):
            pass

        with pytest.raises(RuntimeError, match="reuse sequence point 0"):
            async with sequencer(0):
                pytest.fail("A completed sequence number was reused")

        async with sequencer(1):
            pass

    async def test_reuse_waiting_position(self) -> None:
        sequencer = anyio.Sequencer()
        entered = False

        async def worker() -> None:
            nonlocal entered
            async with sequencer(1):
                entered = True

        async with create_task_group() as tg:
            tg.start_soon(worker)
            await wait_all_tasks_blocked()
            with pytest.raises(RuntimeError, match="reuse sequence point 1"):
                async with sequencer(1):
                    pytest.fail("A waiting sequence number was reused")

            assert not entered
            async with sequencer(0):
                pass

        assert entered

    async def test_cancelled_wait_breaks_sequence(self) -> None:
        sequencer = anyio.Sequencer()
        errors: dict[int, str] = {}

        async def worker(
            position: int, *, task_status: TaskStatus[anyio.CancelScope]
        ) -> None:
            with anyio.CancelScope() as scope:
                task_status.started(scope)
                try:
                    async with sequencer(position):
                        pytest.fail("A broken sequence was entered")
                except RuntimeError as exc:
                    errors[position] = str(exc)

        async with create_task_group() as tg:
            scope = await tg.start(worker, 1)
            await tg.start(worker, 2)
            await wait_all_tasks_blocked()
            scope.cancel()

        assert errors == {
            1: "Sequencer wait cancelled -- sequence broken",
            2: "sequence broken!",
        }
        for position in (0, 3):
            with pytest.raises(RuntimeError, match="sequence broken"):
                async with sequencer(position):
                    pytest.fail("A broken sequence was entered")

    async def test_exception_in_block_releases_next(self) -> None:
        sequencer = anyio.Sequencer()
        error = ValueError("test error")
        entered = False

        async def worker() -> None:
            nonlocal entered
            async with sequencer(1):
                entered = True

        async with create_task_group() as tg:
            tg.start_soon(worker)
            await wait_all_tasks_blocked()
            with pytest.raises(ValueError) as exc:
                async with sequencer(0):
                    raise error

            assert exc.value is error

        assert entered

    async def test_cancellation_in_block_releases_next(self) -> None:
        sequencer = anyio.Sequencer()
        entered = False

        async def worker() -> None:
            nonlocal entered
            async with sequencer(1):
                entered = True

        async with create_task_group() as tg:
            tg.start_soon(worker)
            await wait_all_tasks_blocked()
            with anyio.CancelScope() as scope:
                async with sequencer(0):
                    scope.cancel()
                    await anyio.lowlevel.checkpoint()
                    pytest.fail("Cancellation was not propagated")

            assert scope.cancelled_caught

        assert entered
        async with sequencer(2):
            pass

    def test_create_without_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        sequencer = anyio.Sequencer()

        async def main() -> None:
            async with sequencer(0):
                pass

            async with sequencer(1):
                pass

        anyio.run(
            main, backend=anyio_backend_name, backend_options=anyio_backend_options
        )
