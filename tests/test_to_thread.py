from __future__ import annotations

import asyncio
import threading
import time
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import ContextVar
from functools import partial
from typing import Any, NoReturn

import pytest
import sniffio

import anyio.to_thread
from anyio import (
    CapacityLimiter,
    Event,
    create_task_group,
    from_thread,
    sleep,
    to_thread,
    wait_all_tasks_blocked,
)
from anyio.from_thread import BlockingPortalProvider

pytestmark = pytest.mark.anyio


async def test_run_in_thread_cancelled() -> None:
    state = 0

    def thread_worker() -> None:
        nonlocal state
        state = 2

    async def worker() -> None:
        nonlocal state
        state = 1
        await to_thread.run_sync(thread_worker)
        state = 3

    async with create_task_group() as tg:
        tg.start_soon(worker)
        tg.cancel_scope.cancel()

    assert state == 1


async def test_run_in_thread_exception() -> None:
    def thread_worker() -> NoReturn:
        raise ValueError("foo")

    with pytest.raises(ValueError) as exc:
        await to_thread.run_sync(thread_worker)

    exc.match("^foo$")


async def test_run_in_custom_limiter() -> None:
    max_active_threads = 0

    def thread_worker() -> None:
        nonlocal max_active_threads
        active_threads.add(threading.current_thread())
        max_active_threads = max(max_active_threads, len(active_threads))
        event.wait(1)
        active_threads.remove(threading.current_thread())

    async def task_worker() -> None:
        await to_thread.run_sync(thread_worker, limiter=limiter)

    event = threading.Event()
    limiter = CapacityLimiter(3)
    active_threads: set[threading.Thread] = set()
    async with create_task_group() as tg:
        for _ in range(4):
            tg.start_soon(task_worker)

        await sleep(0.1)
        assert len(active_threads) == 3
        assert limiter.borrowed_tokens == 3
        event.set()

    assert len(active_threads) == 0
    assert max_active_threads == 3


@pytest.mark.parametrize(
    "abandon_on_cancel, expected_last_active",
    [
        pytest.param(False, "task", id="noabandon"),
        pytest.param(True, "thread", id="abandon"),
    ],
)
async def test_cancel_worker_thread(
    abandon_on_cancel: bool, expected_last_active: str
) -> None:
    """
    Test that when a task running a worker thread is cancelled, the cancellation is not
    acted on until the thread finishes.

    """
    last_active: str | None = None

    def thread_worker() -> None:
        nonlocal last_active
        from_thread.run_sync(sleep_event.set)
        time.sleep(0.2)
        last_active = "thread"
        from_thread.run_sync(finish_event.set)

    async def task_worker() -> None:
        nonlocal last_active
        try:
            await to_thread.run_sync(thread_worker, abandon_on_cancel=abandon_on_cancel)
        finally:
            last_active = "task"

    sleep_event = Event()
    finish_event = Event()
    async with create_task_group() as tg:
        tg.start_soon(task_worker)
        await sleep_event.wait()
        tg.cancel_scope.cancel()

    await finish_event.wait()
    assert last_active == expected_last_active


async def test_cancel_wait_on_thread() -> None:
    event = threading.Event()
    future: Future[bool] = Future()

    def wait_event() -> None:
        future.set_result(event.wait(1))

    async with create_task_group() as tg:
        tg.start_soon(partial(to_thread.run_sync, abandon_on_cancel=True), wait_event)
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    await to_thread.run_sync(event.set)
    assert future.result(1)


async def test_deprecated_cancellable_param() -> None:
    with pytest.warns(DeprecationWarning, match="The `cancellable=`"):
        await to_thread.run_sync(bool, cancellable=True)


async def test_contextvar_propagation() -> None:
    var = ContextVar("var", default=1)
    var.set(6)
    assert await to_thread.run_sync(var.get) == 6


async def test_asynclib_detection() -> None:
    with pytest.raises(sniffio.AsyncLibraryNotFoundError):
        await to_thread.run_sync(sniffio.current_async_library)


@pytest.mark.parametrize("anyio_backend", ["asyncio"])
async def test_asyncio_cancel_native_task() -> None:
    task: asyncio.Task[None] | None = None

    async def run_in_thread() -> None:
        nonlocal task
        task = asyncio.current_task()
        await to_thread.run_sync(time.sleep, 0.2, abandon_on_cancel=True)

    async with create_task_group() as tg:
        tg.start_soon(run_in_thread)
        await wait_all_tasks_blocked()
        assert task is not None
        task.cancel()


def test_asyncio_no_root_task(asyncio_event_loop: asyncio.AbstractEventLoop) -> None:
    """
    Regression test for #264.

    Ensures that to_thread.run_sync() does not raise an error when there is no root
    task, but instead tries to find the top most parent task by traversing the cancel
    scope tree, or failing that, uses the current task to set up a shutdown callback.

    """

    async def run_in_thread() -> None:
        try:
            await to_thread.run_sync(time.sleep, 0)
        finally:
            asyncio_event_loop.call_soon(asyncio_event_loop.stop)

    task = asyncio_event_loop.create_task(run_in_thread())
    asyncio_event_loop.run_forever()
    task.result()

    # Wait for worker threads to exit
    for t in threading.enumerate():
        if t.name == "AnyIO worker thread":
            t.join(2)
            assert not t.is_alive()


def test_asyncio_future_callback_partial(
    asyncio_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """
    Regression test for #272.

    Ensures that futures with partial callbacks are handled correctly when the root task
    cannot be determined.
    """

    def func(future: object) -> None:
        pass

    async def sleep_sync() -> None:
        return await to_thread.run_sync(time.sleep, 0)

    task = asyncio_event_loop.create_task(sleep_sync())
    task.add_done_callback(partial(func))
    asyncio_event_loop.run_until_complete(task)


def test_asyncio_run_sync_no_asyncio_run(
    asyncio_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Test that the thread pool shutdown callback does not raise an exception."""

    def exception_handler(loop: object, context: Any = None) -> None:
        exceptions.append(context["exception"])

    exceptions: list[BaseException] = []
    asyncio_event_loop.set_exception_handler(exception_handler)
    asyncio_event_loop.run_until_complete(to_thread.run_sync(time.sleep, 0))
    assert not exceptions


def test_asyncio_run_sync_multiple(
    asyncio_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Regression test for #304."""
    asyncio_event_loop.call_later(0.5, asyncio_event_loop.stop)
    for _ in range(3):
        asyncio_event_loop.run_until_complete(to_thread.run_sync(time.sleep, 0))

    for t in threading.enumerate():
        if t.name == "AnyIO worker thread":
            t.join(2)
            assert not t.is_alive()


def test_asyncio_no_recycle_stopping_worker(
    asyncio_event_loop: asyncio.AbstractEventLoop,
) -> None:
    """Regression test for #323."""

    async def taskfunc1() -> None:
        await anyio.to_thread.run_sync(time.sleep, 0)
        event1.set()
        await event2.wait()

    async def taskfunc2() -> None:
        await event1.wait()
        asyncio_event_loop.call_soon(event2.set)
        await anyio.to_thread.run_sync(time.sleep, 0)
        # At this point, the worker would be stopped but still in the idle workers pool,
        # so the following would hang prior to the fix
        await anyio.to_thread.run_sync(time.sleep, 0)

    event1 = asyncio.Event()
    event2 = asyncio.Event()
    task1 = asyncio_event_loop.create_task(taskfunc1())
    task2 = asyncio_event_loop.create_task(taskfunc2())
    asyncio_event_loop.run_until_complete(asyncio.gather(task1, task2))


async def test_stopiteration() -> None:
    """
    Test that raising StopIteration in a worker thread raises a RuntimeError on the
    caller.

    """

    def raise_stopiteration() -> NoReturn:
        raise StopIteration

    with pytest.raises(RuntimeError, match="coroutine raised StopIteration"):
        await to_thread.run_sync(raise_stopiteration)


class TestBlockingPortalProvider:
    @pytest.fixture
    def provider(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> BlockingPortalProvider:
        return BlockingPortalProvider(
            backend=anyio_backend_name, backend_options=anyio_backend_options
        )

    def test_single_thread(
        self, provider: BlockingPortalProvider, anyio_backend_name: str
    ) -> None:
        threads: set[threading.Thread] = set()

        async def check_thread() -> None:
            assert sniffio.current_async_library() == anyio_backend_name
            threads.add(threading.current_thread())

        active_threads_before = threading.active_count()
        for _ in range(3):
            with provider as portal:
                portal.call(check_thread)

        assert len(threads) == 3
        assert threading.active_count() == active_threads_before

    def test_single_thread_overlapping(
        self, provider: BlockingPortalProvider, anyio_backend_name: str
    ) -> None:
        threads: set[threading.Thread] = set()

        async def check_thread() -> None:
            assert sniffio.current_async_library() == anyio_backend_name
            threads.add(threading.current_thread())

        with provider as portal1:
            with provider as portal2:
                assert portal1 is portal2
                portal2.call(check_thread)

            portal1.call(check_thread)

        assert len(threads) == 1

    def test_multiple_threads(
        self, provider: BlockingPortalProvider, anyio_backend_name: str
    ) -> None:
        threads: set[threading.Thread] = set()
        event = Event()

        async def check_thread() -> None:
            assert sniffio.current_async_library() == anyio_backend_name
            await event.wait()
            threads.add(threading.current_thread())

        def dummy() -> None:
            with provider as portal:
                portal.call(check_thread)

        with ThreadPoolExecutor(max_workers=3) as pool:
            for _ in range(3):
                pool.submit(dummy)

            with provider as portal:
                portal.call(wait_all_tasks_blocked)
                portal.call(event.set)

        assert len(threads) == 1
