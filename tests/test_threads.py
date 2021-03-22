import asyncio
import sys
import threading
import time
from concurrent.futures import CancelledError
from contextlib import suppress

import pytest

from anyio import (
    CapacityLimiter, Event, create_blocking_portal, create_task_group, get_cancelled_exc_class,
    get_current_task, run, run_async_from_thread, run_sync_from_thread, run_sync_in_worker_thread,
    sleep, start_blocking_portal, wait_all_tasks_blocked)

if sys.version_info < (3, 7):
    current_task = asyncio.Task.current_task
else:
    current_task = asyncio.current_task

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


async def test_run_sync_from_thread():
    def add(a, b):
        assert threading.get_ident() == event_loop_thread_id
        return a + b

    def worker(a, b):
        assert threading.get_ident() != event_loop_thread_id
        return run_sync_from_thread(add, a, b)

    event_loop_thread_id = threading.get_ident()
    result = await run_sync_in_worker_thread(worker, 1, 2)
    assert result == 3


def test_run_sync_from_thread_pooling():
    async def main():
        thread_ids = set()
        for _ in range(5):
            thread_ids.add(await run_sync_in_worker_thread(threading.get_ident))

        # Expects that all the work has been done in the same worker thread
        assert len(thread_ids) == 1
        assert thread_ids.pop() != threading.get_ident()
        assert threading.active_count() == initial_count + 1

    # The thread should not exist after the event loop has been closed
    initial_count = threading.active_count()
    run(main, backend='asyncio')
    assert threading.active_count() == initial_count


async def test_run_async_from_thread_exception():
    async def add(a, b):
        assert threading.get_ident() == event_loop_thread_id
        return a + b

    def worker(a, b):
        assert threading.get_ident() != event_loop_thread_id
        return run_async_from_thread(add, a, b)

    event_loop_thread_id = threading.get_ident()
    with pytest.raises(TypeError) as exc:
        await run_sync_in_worker_thread(worker, 1, 'foo')

    exc.match("unsupported operand type")


async def test_run_sync_from_thread_exception():
    def add(a, b):
        assert threading.get_ident() == event_loop_thread_id
        return a + b

    def worker(a, b):
        assert threading.get_ident() != event_loop_thread_id
        return run_sync_from_thread(add, a, b)

    event_loop_thread_id = threading.get_ident()
    with pytest.raises(TypeError) as exc:
        await run_sync_in_worker_thread(worker, 1, 'foo')

    exc.match("unsupported operand type")


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
        tg.spawn(worker)
        tg.cancel_scope.cancel()

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


def test_run_async_from_unclaimed_thread():
    async def foo():
        pass

    exc = pytest.raises(RuntimeError, run_async_from_thread, foo)
    exc.match('This function can only be run from an AnyIO worker thread')


def test_run_sync_from_unclaimed_thread():
    def foo():
        pass

    exc = pytest.raises(RuntimeError, run_sync_from_thread, foo)
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
        run_sync_from_thread(sleep_event.set)
        time.sleep(0.2)
        last_active = 'thread'
        run_sync_from_thread(finish_event.set)

    async def task_worker():
        nonlocal last_active
        try:
            await run_sync_in_worker_thread(thread_worker, cancellable=cancellable)
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
        await run_sync_in_worker_thread(time.sleep, 1, cancellable=True)

    task = None
    async with create_task_group() as tg:
        tg.spawn(run_in_thread)
        await wait_all_tasks_blocked()
        task.cancel()


class TestBlockingPortal:
    class AsyncCM:
        def __init__(self, ignore_error):
            self.ignore_error = ignore_error

        async def __aenter__(self):
            return 'test'

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return self.ignore_error

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

    def test_start_with_new_event_loop(self, anyio_backend_name, anyio_backend_options):
        async def async_get_thread_id():
            return threading.get_ident()

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            thread_id = portal.call(async_get_thread_id)

        assert isinstance(thread_id, int)
        assert thread_id != threading.get_ident()

    def test_start_with_nonexistent_backend(self):
        with pytest.raises(LookupError) as exc:
            with start_blocking_portal('foo'):
                pass

        exc.match('No such backend: foo')

    def test_call_stopped_portal(self, anyio_backend_name, anyio_backend_options):
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            pass

        pytest.raises(RuntimeError, portal.call, threading.get_ident).\
            match('This portal is not running')

    def test_spawn_task(self, anyio_backend_name, anyio_backend_options):
        async def event_waiter():
            await event1.wait()
            event2.set()
            return 'test'

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            event1 = portal.call(Event)
            event2 = portal.call(Event)
            future = portal.spawn_task(event_waiter)
            portal.call(event1.set)
            portal.call(event2.wait)
            assert future.result() == 'test'

    def test_spawn_task_cancel_later(self, anyio_backend_name, anyio_backend_options):
        async def noop():
            await sleep(2)

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future = portal.spawn_task(noop)
            portal.call(wait_all_tasks_blocked)
            future.cancel()

        assert future.cancelled()

    def test_spawn_task_cancel_immediately(self, anyio_backend_name, anyio_backend_options):
        async def event_waiter():
            nonlocal cancelled
            try:
                await sleep(3)
            except get_cancelled_exc_class():
                cancelled = True

        cancelled = False
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future = portal.spawn_task(event_waiter)
            future.cancel()

        assert cancelled

    def test_spawn_task_with_name(self, anyio_backend_name, anyio_backend_options):
        async def taskfunc():
            nonlocal task_name
            task_name = get_current_task().name

        task_name = None
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            portal.spawn_task(taskfunc, name='testname')

        assert task_name == 'testname'

    def test_async_context_manager_success(self, anyio_backend_name, anyio_backend_options):
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with portal.wrap_async_context_manager(TestBlockingPortal.AsyncCM(False)) as cm:
                assert cm == 'test'

    def test_async_context_manager_error(self, anyio_backend_name, anyio_backend_options):
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(Exception) as exc:
                with portal.wrap_async_context_manager(TestBlockingPortal.AsyncCM(False)) as cm:
                    assert cm == 'test'
                    raise Exception('should NOT be ignored')

                exc.match('should NOT be ignored')

    def test_async_context_manager_error_ignore(self, anyio_backend_name, anyio_backend_options):
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with portal.wrap_async_context_manager(TestBlockingPortal.AsyncCM(True)) as cm:
                assert cm == 'test'
                raise Exception('should be ignored')

    def test_start_no_value(self, anyio_backend_name, anyio_backend_options):
        def taskfunc(*, task_status):
            task_status.started()

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, value = portal.start_task(taskfunc)
            assert value is None
            assert future.result() is None

    def test_start_with_value(self, anyio_backend_name, anyio_backend_options):
        def taskfunc(*, task_status):
            task_status.started('foo')

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, value = portal.start_task(taskfunc)
            assert value == 'foo'
            assert future.result() is None

    def test_start_crash_before_started_call(self, anyio_backend_name, anyio_backend_options):
        def taskfunc(*, task_status):
            raise Exception('foo')

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(Exception, match='foo'):
                portal.start_task(taskfunc)

    def test_start_crash_after_started_call(self, anyio_backend_name, anyio_backend_options):
        def taskfunc(*, task_status):
            task_status.started(2)
            raise Exception('foo')

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, value = portal.start_task(taskfunc)
            assert value == 2
            with pytest.raises(Exception, match='foo'):
                future.result()

    def test_start_no_started_call(self, anyio_backend_name, anyio_backend_options):
        def taskfunc(*, task_status):
            pass

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(RuntimeError, match='Task exited'):
                portal.start_task(taskfunc)

    def test_start_with_name(self, anyio_backend_name, anyio_backend_options):
        def taskfunc(*, task_status):
            task_status.started(get_current_task().name)

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, start_value = portal.start_task(taskfunc, name='testname')
            assert start_value == 'testname'
