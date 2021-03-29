import signal
import sys
import threading

import pytest

from anyio import (
    CancelScope, CapacityLimiter, Condition, Event, Lock, Semaphore, TaskInfo,
    create_memory_object_stream, create_task_group, current_default_worker_thread_limiter,
    current_effective_deadline, current_time, fail_after, get_current_task, get_running_tasks,
    maybe_async, maybe_async_cm, move_on_after, open_signal_receiver, run_async_from_thread,
    run_sync_from_thread, run_sync_in_worker_thread, sleep, to_thread)

pytestmark = pytest.mark.anyio


class TestMaybeAsync:
    async def test_cancel_scope(self):
        with CancelScope() as scope:
            await maybe_async(scope.cancel())

    async def test_current_time(self):
        value = await maybe_async(current_time())
        assert type(value) is float

    async def test_current_effective_deadline(self):
        value = await maybe_async(current_effective_deadline())
        assert type(value) is float

    async def test_get_running_tasks(self):
        tasks = await maybe_async(get_running_tasks())
        assert type(tasks) is list


async def test_maybe_async_cm():
    async with maybe_async_cm(CancelScope()):
        pass


class TestDeprecations:
    async def test_current_effective_deadlinee(self):
        with pytest.deprecated_call():
            deadline = await current_effective_deadline()

        assert isinstance(deadline, float)

    async def test_current_time(self):
        with pytest.deprecated_call():
            timestamp = await current_time()

        assert isinstance(timestamp, float)

    async def test_get_current_task(self):
        with pytest.deprecated_call():
            task = await get_current_task()

        assert isinstance(task, TaskInfo)

    async def test_running_tasks(self):
        with pytest.deprecated_call():
            tasks = await get_running_tasks()

        assert tasks
        assert all(isinstance(task, TaskInfo) for task in tasks)

    @pytest.mark.skipif(sys.platform == 'win32',
                        reason='Signal delivery cannot be tested on Windows')
    async def test_open_signal_receiver(self):
        with pytest.deprecated_call():
            async with open_signal_receiver(signal.SIGINT):
                pass

    async def test_cancelscope_cancel(self):
        with CancelScope() as scope:
            with pytest.deprecated_call():
                await scope.cancel()

    async def test_taskgroup_cancel(self):
        async with create_task_group() as tg:
            with pytest.deprecated_call():
                await tg.cancel_scope.cancel()

    async def test_capacitylimiter_acquire_nowait(self):
        limiter = CapacityLimiter(1)
        with pytest.deprecated_call():
            await limiter.acquire_nowait()

    async def test_capacitylimiter_acquire_on_behalf_of_nowait(self):
        limiter = CapacityLimiter(1)
        with pytest.deprecated_call():
            await limiter.acquire_on_behalf_of_nowait(object())

    async def test_capacitylimiter_set_total_tokens(self):
        limiter = CapacityLimiter(1)
        with pytest.deprecated_call():
            await limiter.set_total_tokens(3)

        assert limiter.total_tokens == 3

    async def test_condition_release(self):
        condition = Condition()
        condition.acquire_nowait()
        with pytest.deprecated_call():
            await condition.release()

    async def test_event_set(self):
        event = Event()
        with pytest.deprecated_call():
            await event.set()

    async def test_lock_release(self):
        lock = Lock()
        lock.acquire_nowait()
        with pytest.deprecated_call():
            await lock.release()

    async def test_memory_object_stream_send_nowait(self):
        send, receive = create_memory_object_stream(1)
        with pytest.deprecated_call():
            await send.send_nowait(None)

    async def test_semaphore_release(self):
        semaphore = Semaphore(1)
        semaphore.acquire_nowait()
        with pytest.deprecated_call():
            await semaphore.release()

    async def test_taskgroup_spawn(self):
        async with create_task_group() as tg:
            with pytest.deprecated_call():
                await tg.spawn(sleep, 0)

    async def test_move_on_after(self):
        with pytest.deprecated_call():
            async with move_on_after(0):
                pass

    async def test_fail_after(self):
        with pytest.raises(TimeoutError), pytest.deprecated_call():
            async with fail_after(0):
                pass

    async def test_run_sync_in_worker_thread(self):
        with pytest.deprecated_call():
            thread_id = await run_sync_in_worker_thread(threading.get_ident)
            assert thread_id != threading.get_ident()

    async def test_run_async_from_thread(self):
        async def get_ident():
            return threading.get_ident()

        def thread_func():
            with pytest.deprecated_call():
                return run_async_from_thread(get_ident)

        assert await to_thread.run_sync(thread_func) == threading.get_ident()

    async def test_run_sync_from_thread(self):
        def thread_func():
            with pytest.deprecated_call():
                return run_sync_from_thread(threading.get_ident)

        assert await to_thread.run_sync(thread_func) == threading.get_ident()

    async def test_current_default_worker_thread_limiter(self):
        with pytest.deprecated_call():
            default_limiter = to_thread.current_default_thread_limiter()
            assert current_default_worker_thread_limiter() is default_limiter
