from __future__ import annotations

import asyncio
import gc
import os
import subprocess
import sys
import threading
import time
import weakref
from collections.abc import Iterator
from concurrent.futures import Future, ThreadPoolExecutor
from contextvars import Context, ContextVar
from functools import partial
from textwrap import dedent
from typing import Any, NoReturn

import pytest
from pytest_mock import MockerFixture

import anyio.to_thread
from anyio import (
    CapacityLimiter,
    Event,
    create_task_group,
    from_thread,
    to_thread,
    wait_all_tasks_blocked,
)
from anyio._core._eventloop import current_async_library
from anyio.from_thread import BlockingPortalProvider
from anyio.lowlevel import checkpoint

from .conftest import asyncio_params, no_other_refs


@pytest.fixture
def asyncio_worker_pool(mocker: MockerFixture) -> Iterator[Any]:
    from anyio._backends import _asyncio

    pool = _asyncio.WorkerThreadPool()
    mocker.patch.object(_asyncio, "_threadpool", pool)
    # Reuse tests must not race an artificially short idle deadline.
    mocker.patch.object(_asyncio.WorkerThread, "MAX_IDLE_TIME", 60)
    yield pool
    loop = asyncio.new_event_loop()
    future = loop.create_future()
    future.cancel()
    loop.close()
    with pool.lock:
        workers = list(pool.workers)
        for worker in workers:
            mocker.patch.object(worker, "MAX_IDLE_TIME", 0.1)
            if worker in pool.idle_workers:
                del pool.idle_workers[worker]
                # Wake an idle worker so its next wait uses the cleanup timeout.
                worker.queue.put_nowait(
                    (Context(), int, (), future, _asyncio.CancelScope())
                )

    for worker in workers:
        worker.join()


@pytest.mark.parametrize("anyio_backend", asyncio_params)
def test_asyncio_worker_pool_loop_closure(
    asyncio_worker_pool: Any, anyio_backend_options: dict[str, Any]
) -> None:
    workers: list[Any] = []
    loop_factory = anyio_backend_options.get("loop_factory", asyncio.new_event_loop)
    for iteration in range(3):
        loop = loop_factory()
        try:
            if iteration == 2:
                # Wake the reused worker with one final job before checking that
                # it retires without further submissions or loop cleanup.
                workers[0].MAX_IDLE_TIME = 0.1

            workers.append(
                loop.run_until_complete(to_thread.run_sync(threading.current_thread))
            )
            workers[-1].queue.join()
        finally:
            # Deliberately skip shutdown_asyncgens() and any runner cleanup.
            loop.close()

    assert workers[0] is workers[1] is workers[2]
    workers[0].join()
    assert not asyncio_worker_pool.workers
    assert not asyncio_worker_pool.idle_workers

    replacement = anyio.run(to_thread.run_sync, threading.current_thread)
    assert replacement is not workers[0]


def test_asyncio_worker_pool_concurrent_loops(asyncio_worker_pool: Any) -> None:
    barrier = threading.Barrier(3)
    value = ContextVar("value", default=-1)

    def worker(expected: int, loop: asyncio.AbstractEventLoop) -> threading.Thread:
        barrier.wait(5)
        assert value.get() == expected
        assert from_thread.run_sync(asyncio.get_running_loop) is loop
        value.set(-2)
        return threading.current_thread()

    async def main(expected: int) -> threading.Thread:
        value.set(expected)
        result = await to_thread.run_sync(worker, expected, asyncio.get_running_loop())
        assert value.get() == expected
        return result

    with ThreadPoolExecutor(3) as executor:
        futures = [executor.submit(anyio.run, main, n) for n in range(3)]
        workers = [future.result(5) for future in futures]

    assert len(set(workers)) == 3


@pytest.mark.parametrize("anyio_backend", asyncio_params)
async def test_asyncio_worker_pool_assignment_during_retirement(
    asyncio_worker_pool: Any, mocker: MockerFixture
) -> None:
    from queue import Empty

    worker: Any = await to_thread.run_sync(threading.current_thread)
    worker.queue.join()
    timed_out = threading.Event()
    release_timeout = threading.Event()
    original_get = worker.queue.get

    def get(*args: Any, **kwargs: Any) -> Any:
        try:
            return original_get(*args, **kwargs)
        except Empty:
            timed_out.set()
            assert release_timeout.wait(5)
            raise

    mocker.patch.object(worker.queue, "get", side_effect=get)
    try:
        worker.MAX_IDLE_TIME = 0.1
        # The current queue.get() may already be waiting; run a job so that the
        # next idle wait uses the patched method.
        assert await to_thread.run_sync(threading.current_thread) is worker
        while not timed_out.is_set():
            await checkpoint()

        task = asyncio.create_task(to_thread.run_sync(threading.current_thread))
        await wait_all_tasks_blocked()
        release_timeout.set()
        assert await task is worker
    finally:
        release_timeout.set()


def test_asyncio_worker_pool_start_failure(
    asyncio_worker_pool: Any, mocker: MockerFixture
) -> None:
    from anyio._backends._asyncio import WorkerThread

    mocker.patch.object(WorkerThread, "start", side_effect=RuntimeError("cannot start"))

    async def main() -> None:
        await to_thread.run_sync(int)

    with pytest.raises(RuntimeError, match="cannot start"):
        anyio.run(main)

    assert not asyncio_worker_pool.workers
    assert not asyncio_worker_pool.idle_workers


@pytest.mark.skipif(not hasattr(os, "fork"), reason="requires fork")
def test_asyncio_worker_pool_after_fork() -> None:
    script = dedent("""
        import os
        import threading
        import anyio
        from anyio._backends._asyncio import _threadpool

        worker = anyio.run(anyio.to_thread.run_sync, threading.current_thread)
        # A child must replace even a locked inherited pool.
        with _threadpool.lock:
            pid = os.fork()
            if pid == 0:
                try:
                    new_worker = anyio.run(anyio.to_thread.run_sync, threading.current_thread)
                    assert new_worker is not worker
                except BaseException:
                    os._exit(1)
                os._exit(0)

        assert os.waitpid(pid, 0)[1] == 0
    """)
    subprocess.run([sys.executable, "-c", script], check=True, timeout=10)


def test_asyncio_worker_pool_interpreter_shutdown() -> None:
    script = dedent("""
        import threading
        import anyio
        from anyio._backends._asyncio import WorkerThread

        WorkerThread.MAX_IDLE_TIME = 60
        worker = anyio.run(anyio.to_thread.run_sync, threading.current_thread)
        assert worker.daemon
        assert worker.is_alive()
    """)
    subprocess.run([sys.executable, "-c", script], check=True, timeout=5)


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
        if len(active_threads) == 3:
            from_thread.run_sync(threads_started.set)

        event.wait(10)
        active_threads.remove(threading.current_thread())

    async def task_worker() -> None:
        await to_thread.run_sync(thread_worker, limiter=limiter)

    event = threading.Event()
    threads_started = Event()
    limiter = CapacityLimiter(3)
    active_threads: set[threading.Thread] = set()
    async with create_task_group() as tg:
        for _ in range(4):
            tg.start_soon(task_worker)

        await threads_started.wait()
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


def test_asyncio_worker_thread_loop_closed_during_result_report(
    mocker: MockerFixture,
) -> None:
    """Regression test for #1265.

    Pause result delivery after the worker has observed an open event loop, then let
    the runner close the loop before the delivery attempt continues.
    """
    worker_started = threading.Event()
    release_worker = threading.Event()
    result_report_started = threading.Event()
    release_result_report = threading.Event()
    worker_threads: list[threading.Thread] = []

    def thread_worker() -> None:
        worker_threads.append(threading.current_thread())
        worker_started.set()
        assert release_worker.wait(5)

    async def main() -> None:
        loop = asyncio.get_running_loop()
        call_soon_threadsafe = loop.call_soon_threadsafe

        def synchronized_call_soon_threadsafe(
            callback: Any, *args: Any, context: Any = None
        ) -> asyncio.Handle:
            if worker_threads and threading.current_thread() is worker_threads[0]:
                result_report_started.set()
                assert release_result_report.wait(5)

            return call_soon_threadsafe(callback, *args, context=context)

        mocker.patch.object(
            loop,
            "call_soon_threadsafe",
            side_effect=synchronized_call_soon_threadsafe,
        )
        async with create_task_group() as task_group:
            task_group.start_soon(
                partial(to_thread.run_sync, thread_worker, abandon_on_cancel=True)
            )
            while not worker_started.is_set():
                await checkpoint()

            task_group.cancel_scope.cancel()

        release_worker.set()
        while not result_report_started.is_set():
            await checkpoint()

    try:
        anyio.run(main, backend="asyncio")
    finally:
        release_worker.set()
        release_result_report.set()

    worker_threads[0].queue.join()  # type: ignore[attr-defined]
    assert anyio.run(to_thread.run_sync, threading.current_thread) is worker_threads[0]


async def test_cancel_wait_on_thread() -> None:
    event = threading.Event()
    future: Future[bool] = Future()

    def wait_event() -> None:
        future.set_result(event.wait(5))

    async with create_task_group() as tg:
        tg.start_soon(partial(to_thread.run_sync, abandon_on_cancel=True), wait_event)
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    await to_thread.run_sync(event.set)
    assert future.result(5)


async def test_deprecated_cancellable_param() -> None:
    with pytest.warns(DeprecationWarning, match="The `cancellable=`"):
        await to_thread.run_sync(bool, cancellable=True)


async def test_contextvar_propagation() -> None:
    var = ContextVar("var", default=1)
    var.set(6)
    assert await to_thread.run_sync(var.get) == 6


async def test_asynclib_detection() -> None:
    assert await to_thread.run_sync(current_async_library) is None


@pytest.mark.parametrize("anyio_backend", asyncio_params)
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


@pytest.mark.parametrize("anyio_backend", asyncio_params)
async def test_asyncio_worker_reused_after_cancelled_call(
    asyncio_worker_pool: Any,
    mocker: MockerFixture,
) -> None:
    """
    Regression test for a worker thread being leaked when the call was cancelled after
    it had been queued for the worker, but before the worker thread dequeued it.

    Such a worker must be returned to the idle worker pool so that it gets reused by
    later calls, and retire automatically when idle for too long.
    """
    worker: Any = await to_thread.run_sync(threading.current_thread)
    # Simulate a scheduling delay longer than the retirement tests' timeout.
    await asyncio.sleep(0.2)

    def put_cancelled_item(item: tuple[Any, ...]) -> None:
        # Cancel the future before the worker thread gets a chance to dequeue the item
        item[3].cancel()
        original_put_nowait(item)

    original_put_nowait = worker.queue.put_nowait
    queue_patch = mocker.patch.object(
        worker.queue, "put_nowait", side_effect=put_cancelled_item
    )
    with pytest.raises(asyncio.CancelledError):
        await to_thread.run_sync(int)

    mocker.stop(queue_patch)

    # Wait for the worker to finish the cancelled job and return to the idle pool.
    worker.queue.join()

    # The next call should reuse that worker rather than start a new one
    assert await to_thread.run_sync(threading.current_thread) is worker


def test_asyncio_no_root_task(asyncio_event_loop: asyncio.AbstractEventLoop) -> None:
    """
    Regression test for #264.

    Ensures that to_thread.run_sync() works with a manually managed loop without a
    root task.

    """

    async def run_in_thread() -> None:
        try:
            await to_thread.run_sync(time.sleep, 0)
        finally:
            asyncio_event_loop.call_soon(asyncio_event_loop.stop)

    task = asyncio_event_loop.create_task(run_in_thread())
    asyncio_event_loop.run_forever()
    task.result()


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
    workers = [
        asyncio_event_loop.run_until_complete(
            to_thread.run_sync(threading.current_thread)
        )
        for _ in range(3)
    ]
    assert workers[0] is workers[1] is workers[2]


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
        # Completing the other task must not prevent subsequent worker calls.
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
            assert current_async_library() == anyio_backend_name
            threads.add(threading.current_thread())

        for _ in range(3):
            with provider as portal:
                portal.call(check_thread)

        assert len(threads) == 3
        assert all(not thread.is_alive() for thread in threads)

    def test_single_thread_overlapping(
        self, provider: BlockingPortalProvider, anyio_backend_name: str
    ) -> None:
        threads: set[threading.Thread] = set()

        async def check_thread() -> None:
            assert current_async_library() == anyio_backend_name
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
            assert current_async_library() == anyio_backend_name
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


skipif_pypy_mark = pytest.mark.skipif(
    sys.implementation.name == "pypy",
    reason=(
        "gc.get_referrers is broken on PyPy (see "
        "https://github.com/pypy/pypy/issues/5075)"
    ),
)


@skipif_pypy_mark
async def test_run_sync_worker_cyclic_references() -> None:
    class Foo:
        pass

    def foo(_: Foo) -> None:
        pass

    cvar = ContextVar[Foo]("cvar")
    contextval = Foo()
    arg = Foo()
    cvar.set(contextval)
    await to_thread.run_sync(foo, arg)
    cvar.set(Foo())
    gc.collect()
    await checkpoint()

    assert gc.get_referrers(contextval) == no_other_refs()
    assert gc.get_referrers(foo) == no_other_refs()
    assert gc.get_referrers(arg) == no_other_refs()


@skipif_pypy_mark
@pytest.mark.parametrize("anyio_backend", asyncio_params)
def test_asyncio_worker_pool_does_not_retain_closed_loops(
    asyncio_worker_pool: Any, anyio_backend_options: dict[str, Any]
) -> None:
    loop_refs = []
    loop_factory = anyio_backend_options.get("loop_factory", asyncio.new_event_loop)
    for _ in range(3):
        loop = loop_factory()
        try:
            worker: Any = loop.run_until_complete(
                to_thread.run_sync(threading.current_thread)
            )
            worker.queue.join()
        finally:
            loop.close()

        loop_refs.append(weakref.ref(loop))
        del loop

    gc.collect()
    assert all(loop_ref() is None for loop_ref in loop_refs)


@skipif_pypy_mark
def test_asyncio_run_does_not_leak_event_loop() -> None:
    """
    Regression test for #1203.

    Ensure worker pool use does not keep the event loop alive.
    """

    def thread_worker() -> None:
        pass

    async def main() -> weakref.ref[object]:
        await to_thread.run_sync(thread_worker)
        return weakref.ref(asyncio.get_running_loop())

    loop_ref = anyio.run(main)

    gc.collect()
    assert loop_ref() is None
