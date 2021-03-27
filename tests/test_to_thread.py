import asyncio
import sys
import threading
import time

import pytest

from anyio import (
    CapacityLimiter, Event, create_task_group, from_thread, sleep, to_thread,
    wait_all_tasks_blocked)

if sys.version_info < (3, 7):
    current_task = asyncio.Task.current_task
else:
    current_task = asyncio.current_task

pytestmark = pytest.mark.anyio


async def test_run_in_thread_cancelled():
    def thread_worker():
        nonlocal state
        state = 2

    async def worker():
        nonlocal state
        state = 1
        await to_thread.run_sync(thread_worker)
        state = 3

    state = 0
    async with create_task_group() as tg:
        tg.spawn(worker)
        tg.cancel_scope.cancel()

    assert state == 1


async def test_run_in_thread_exception():
    def thread_worker():
        raise ValueError('foo')

    with pytest.raises(ValueError) as exc:
        await to_thread.run_sync(thread_worker)

    exc.match('^foo$')


async def test_run_in_custom_limiter():
    def thread_worker():
        nonlocal num_active_threads, max_active_threads
        num_active_threads += 1
        max_active_threads = max(num_active_threads, max_active_threads)
        event.wait(1)
        num_active_threads -= 1

    async def task_worker():
        await to_thread.run_sync(thread_worker, limiter=limiter)

    event = threading.Event()
    num_active_threads = max_active_threads = 0
    limiter = CapacityLimiter(3)
    async with create_task_group() as tg:
        for _ in range(4):
            tg.spawn(task_worker)

        await sleep(0.1)
        assert num_active_threads == 3
        assert limiter.borrowed_tokens == 3
        event.set()

    assert num_active_threads == 0
    assert max_active_threads == 3


@pytest.mark.parametrize('cancellable, expected_last_active', [
    (False, 'task'),
    (True, 'thread')
], ids=['uncancellable', 'cancellable'])
async def test_cancel_worker_thread(cancellable, expected_last_active):
    """
    Test that when a task running a worker thread is cancelled, the cancellation is not acted on
    until the thread finishes.

    """
    def thread_worker():
        nonlocal last_active
        from_thread.run_sync(sleep_event.set)
        time.sleep(0.2)
        last_active = 'thread'
        from_thread.run_sync(finish_event.set)

    async def task_worker():
        nonlocal last_active
        try:
            await to_thread.run_sync(thread_worker, cancellable=cancellable)
        finally:
            last_active = 'task'

    sleep_event = Event()
    finish_event = Event()
    last_active = None
    async with create_task_group() as tg:
        tg.spawn(task_worker)
        await sleep_event.wait()
        tg.cancel_scope.cancel()

    await finish_event.wait()
    assert last_active == expected_last_active


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cancel_asyncio_native_task():
    async def run_in_thread():
        nonlocal task
        task = current_task()
        await to_thread.run_sync(time.sleep, 1, cancellable=True)

    task = None
    async with create_task_group() as tg:
        tg.spawn(run_in_thread)
        await wait_all_tasks_blocked()
        task.cancel()
