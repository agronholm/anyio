import threading
import time

import pytest

from anyio import (
    run_async_from_thread, run_in_thread, create_task_group, sleep, create_capacity_limiter,
    create_event)


@pytest.mark.anyio
async def test_run_async_from_thread():
    async def add(a, b):
        assert threading.get_ident() == event_loop_thread_id
        return a + b

    def worker(a, b):
        assert threading.get_ident() != event_loop_thread_id
        return run_async_from_thread(add, a, b)

    event_loop_thread_id = threading.get_ident()
    result = await run_in_thread(worker, 1, 2)
    assert result == 3


@pytest.mark.anyio
async def test_run_anyio_async_func_from_thread():
    def worker(*args):
        run_async_from_thread(sleep, *args)
        return True

    assert await run_in_thread(worker, 0)


@pytest.mark.anyio
async def test_run_in_thread_cancelled():
    def thread_worker():
        nonlocal state
        state = 2

    async def worker():
        nonlocal state
        state = 1
        await run_in_thread(thread_worker)
        state = 3

    state = 0
    async with create_task_group() as tg:
        await tg.spawn(worker)
        await tg.cancel_scope.cancel()

    assert state == 1


@pytest.mark.anyio
async def test_run_in_thread_exception():
    def thread_worker():
        raise ValueError('foo')

    with pytest.raises(ValueError) as exc:
        await run_in_thread(thread_worker)

    exc.match('^foo$')


@pytest.mark.anyio
async def test_run_in_custom_limiter():
    def thread_worker():
        nonlocal num_active_threads, max_active_threads
        num_active_threads += 1
        max_active_threads = max(num_active_threads, max_active_threads)
        event.wait(1)
        num_active_threads -= 1

    async def task_worker():
        await run_in_thread(thread_worker, limiter=limiter)

    event = threading.Event()
    num_active_threads = max_active_threads = 0
    limiter = create_capacity_limiter(3)
    async with create_task_group() as tg:
        for _ in range(4):
            await tg.spawn(task_worker)

        await sleep(0.1)
        assert num_active_threads == 3
        assert limiter.borrowed_tokens == 3
        event.set()

    assert num_active_threads == 0
    assert max_active_threads == 3


def test_run_async_from_unclaimed_thread():
    async def foo():
        pass

    exc = pytest.raises(RuntimeError, run_async_from_thread, foo)
    exc.match('This function can only be run from an AnyIO worker thread')


@pytest.mark.parametrize('cancellable, expected_last_active', [
    (False, 'task'),
    (True, 'thread')
], ids=['uncancellable', 'cancellable'])
@pytest.mark.anyio
async def test_cancel_worker_thread(cancellable, expected_last_active):
    """
    Test that when a task running a worker thread is cancelled, the cancellation is not acted on
    until the thread finishes.

    """
    def thread_worker():
        nonlocal last_active
        run_async_from_thread(sleep_event.set)
        time.sleep(0.2)
        last_active = 'thread'
        run_async_from_thread(finish_event.set)

    async def task_worker():
        nonlocal last_active
        try:
            await run_in_thread(thread_worker, cancellable=cancellable)
        finally:
            last_active = 'task'

    sleep_event = create_event()
    finish_event = create_event()
    last_active = None
    async with create_task_group() as tg:
        await tg.spawn(task_worker)
        await sleep_event.wait()
        await tg.cancel_scope.cancel()

    await finish_event.wait()
    assert last_active == expected_last_active
