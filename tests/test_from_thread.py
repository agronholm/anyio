import threading
from concurrent.futures import CancelledError
from contextlib import suppress

import pytest

from anyio import (
    Event, create_blocking_portal, from_thread, get_cancelled_exc_class, get_current_task, run,
    sleep, start_blocking_portal, to_thread, wait_all_tasks_blocked)

pytestmark = pytest.mark.anyio


class TestRunAsyncFromThread:
    async def test_run_async_from_thread(self):
        async def add(a, b):
            assert threading.get_ident() == event_loop_thread_id
            return a + b

        def worker(a, b):
            assert threading.get_ident() != event_loop_thread_id
            return from_thread.run(add, a, b)

        event_loop_thread_id = threading.get_ident()
        result = await to_thread.run_sync(worker, 1, 2)
        assert result == 3

    async def test_run_sync_from_thread(self):
        def add(a, b):
            assert threading.get_ident() == event_loop_thread_id
            return a + b

        def worker(a, b):
            assert threading.get_ident() != event_loop_thread_id
            return from_thread.run_sync(add, a, b)

        event_loop_thread_id = threading.get_ident()
        result = await to_thread.run_sync(worker, 1, 2)
        assert result == 3

    def test_run_sync_from_thread_pooling(self):
        async def main():
            thread_ids = set()
            for _ in range(5):
                thread_ids.add(await to_thread.run_sync(threading.get_ident))

            # Expects that all the work has been done in the same worker thread
            assert len(thread_ids) == 1
            assert thread_ids.pop() != threading.get_ident()
            assert threading.active_count() == initial_count + 1

        # The thread should not exist after the event loop has been closed
        initial_count = threading.active_count()
        run(main, backend='asyncio')
        assert threading.active_count() == initial_count

    async def test_run_async_from_thread_exception(self):
        async def add(a, b):
            assert threading.get_ident() == event_loop_thread_id
            return a + b

        def worker(a, b):
            assert threading.get_ident() != event_loop_thread_id
            return from_thread.run(add, a, b)

        event_loop_thread_id = threading.get_ident()
        with pytest.raises(TypeError) as exc:
            await to_thread.run_sync(worker, 1, 'foo')

        exc.match("unsupported operand type")

    async def test_run_sync_from_thread_exception(self):
        def add(a, b):
            assert threading.get_ident() == event_loop_thread_id
            return a + b

        def worker(a, b):
            assert threading.get_ident() != event_loop_thread_id
            return from_thread.run_sync(add, a, b)

        event_loop_thread_id = threading.get_ident()
        with pytest.raises(TypeError) as exc:
            await to_thread.run_sync(worker, 1, 'foo')

        exc.match("unsupported operand type")

    async def test_run_anyio_async_func_from_thread(self):
        def worker(*args):
            from_thread.run(sleep, *args)
            return True

        assert await to_thread.run_sync(worker, 0)

    def test_run_async_from_unclaimed_thread(self):
        async def foo():
            pass

        exc = pytest.raises(RuntimeError, from_thread.run, foo)
        exc.match('This function can only be run from an AnyIO worker thread')


class TestRunSyncFromThread:
    def test_run_sync_from_unclaimed_thread(self):
        def foo():
            pass

        exc = pytest.raises(RuntimeError, from_thread.run_sync, foo)
        exc.match('This function can only be run from an AnyIO worker thread')


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
            await to_thread.run_sync(thread.join)

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

        await to_thread.run_sync(thread1.join)
        await to_thread.run_sync(thread2.join)

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

        await to_thread.run_sync(thread1.join)
        await to_thread.run_sync(thread2.join)

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
