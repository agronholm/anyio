import threading
import time
from concurrent.futures import CancelledError
from contextlib import suppress

import pytest

from anyio import (
    create_blocking_portal, create_capacity_limiter, create_event, create_task_group,
    run_async_from_thread, run_sync_in_worker_thread, sleep, start_blocking_portal)

pytestmark = pytest.mark.anyio


async def test_run_async_from_thread():
    async def add(a, b):
        assert threading.get_ident() == event_loop_thread_id
        return a + b

    def worker(a, b):
        assert threading.get_ident() != event_loop_thread_id
        return run_async_from_thread(add, a, b)

    event_loop_thread_id = threading.get_ident()
    result = await run_sync_in_worker_thread(worker, 1, 2)
    assert result == 3


async def test_run_anyio_async_func_from_thread():
    def worker(*args):
        run_async_from_thread(sleep, *args)
        return True

    assert await run_sync_in_worker_thread(worker, 0)


async def test_run_in_thread_cancelled():
    def thread_worker():
        nonlocal state
        state = 2

    async def worker():
        nonlocal state
        state = 1
        await run_sync_in_worker_thread(thread_worker)
        state = 3

    state = 0
    async with create_task_group() as tg:
        await tg.spawn(worker)
        await tg.cancel_scope.cancel()

    assert state == 1


async def test_run_in_thread_exception():
    def thread_worker():
        raise ValueError('foo')

    with pytest.raises(ValueError) as exc:
        await run_sync_in_worker_thread(thread_worker)

    exc.match('^foo$')


async def test_run_in_custom_limiter():
    def thread_worker():
        nonlocal num_active_threads, max_active_threads
        num_active_threads += 1
        max_active_threads = max(num_active_threads, max_active_threads)
        event.wait(1)
        num_active_threads -= 1

    async def task_worker():
        await run_sync_in_worker_thread(thread_worker, limiter=limiter)

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
            await run_sync_in_worker_thread(thread_worker, cancellable=cancellable)
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


class TestBlockingPortal:
    async def test_successful_call(self):
        async def async_get_thread_id():
            return threading.get_ident()

        def external_thread():
            thread_ids.append(portal.call(threading.get_ident))
            thread_ids.append(portal.call(async_get_thread_id))

        thread_ids = []
        async with create_blocking_portal() as portal:
            thread = threading.Thread(target=external_thread)
            thread.start()
            await run_sync_in_worker_thread(thread.join)

        for thread_id in thread_ids:
            assert thread_id == threading.get_ident()

    async def test_aexit_with_exception(self):
        """Test that when the portal exits with an exception, all tasks are cancelled."""
        def external_thread():
            try:
                portal.call(sleep, 3)
            except BaseException as exc:
                results.append(exc)
            else:
                results.append(None)

        results = []
        with suppress(Exception):
            async with create_blocking_portal() as portal:
                thread1 = threading.Thread(target=external_thread)
                thread1.start()
                thread2 = threading.Thread(target=external_thread)
                thread2.start()
                await sleep(0.1)
                assert not results
                raise Exception

        await run_sync_in_worker_thread(thread1.join)
        await run_sync_in_worker_thread(thread2.join)

        assert len(results) == 2
        assert isinstance(results[0], CancelledError)
        assert isinstance(results[1], CancelledError)

    async def test_aexit_without_exception(self):
        """Test that when the portal exits, it waits for all tasks to finish."""
        def external_thread():
            try:
                portal.call(sleep, 0.2)
            except BaseException as exc:
                results.append(exc)
            else:
                results.append(None)

        results = []
        async with create_blocking_portal() as portal:
            thread1 = threading.Thread(target=external_thread)
            thread1.start()
            thread2 = threading.Thread(target=external_thread)
            thread2.start()
            await sleep(0.1)
            assert not results

        await run_sync_in_worker_thread(thread1.join)
        await run_sync_in_worker_thread(thread2.join)

        assert results == [None, None]

    async def test_call_portal_from_event_loop_thread(self):
        async with create_blocking_portal() as portal:
            exc = pytest.raises(RuntimeError, portal.call, threading.get_ident)
            exc.match('This method cannot be called from the event loop thread')

    @pytest.mark.parametrize('use_contextmanager', [False, True],
                             ids=['contextmanager', 'startstop'])
    def test_start_with_new_event_loop(self, anyio_backend_name, anyio_backend_options,
                                       use_contextmanager):
        async def async_get_thread_id():
            return threading.get_ident()

        if use_contextmanager:
            with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
                thread_id = portal.call(async_get_thread_id)
        else:
            portal = start_blocking_portal(anyio_backend_name, anyio_backend_options)
            try:
                thread_id = portal.call(async_get_thread_id)
            finally:
                portal.call(portal.stop)

        assert isinstance(thread_id, int)
        assert thread_id != threading.get_ident()

    def test_call_stopped_portal(self, anyio_backend_name, anyio_backend_options):
        portal = start_blocking_portal(anyio_backend_name, anyio_backend_options)
        portal.call(portal.stop)
        pytest.raises(RuntimeError, portal.call, threading.get_ident).\
            match('This portal is not running')
