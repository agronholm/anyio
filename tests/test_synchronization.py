import pytest

from anyio import (
    create_capacity_limiter, create_condition, create_event, create_lock, create_semaphore,
    create_task_group, current_default_worker_thread_limiter, open_cancel_scope,
    wait_all_tasks_blocked)
from anyio.abc import CapacityLimiter

pytestmark = pytest.mark.anyio


class TestLock:
    async def test_contextmanager(self):
        async def task():
            assert lock.locked()
            async with lock:
                results.append('2')

        results = []
        lock = create_lock()
        async with create_task_group() as tg:
            async with lock:
                await tg.spawn(task)
                await wait_all_tasks_blocked()
                results.append('1')

        assert not lock.locked()
        assert results == ['1', '2']

    async def test_manual_acquire(self):
        async def task():
            assert lock.locked()
            await lock.acquire()
            try:
                results.append('2')
            finally:
                await lock.release()

        results = []
        lock = create_lock()
        async with create_task_group() as tg:
            await lock.acquire()
            try:
                await tg.spawn(task)
                await wait_all_tasks_blocked()
                results.append('1')
            finally:
                await lock.release()

        assert not lock.locked()
        assert results == ['1', '2']

    async def test_cancel(self):
        async def task():
            nonlocal task_started, got_lock
            task_started = True
            async with lock:
                got_lock = True

        task_started = got_lock = False
        lock = create_lock()
        async with create_task_group() as tg:
            async with lock:
                await tg.spawn(task)
                await tg.cancel_scope.cancel()

        assert task_started
        assert not got_lock


class TestEvent:
    async def test_event(self):
        async def setter():
            assert not event.is_set()
            await event.set()

        event = create_event()
        async with create_task_group() as tg:
            await tg.spawn(setter)
            await event.wait()

        assert event.is_set()

    async def test_event_cancel(self):
        async def task():
            nonlocal task_started, event_set
            task_started = True
            await event.wait()
            event_set = True

        task_started = event_set = False
        event = create_event()
        async with create_task_group() as tg:
            await tg.spawn(task)
            await tg.cancel_scope.cancel()
            await event.set()

        assert task_started
        assert not event_set


class TestCondition:
    async def test_contextmanager(self):
        async def notifier():
            async with condition:
                await condition.notify_all()

        condition = create_condition()
        async with create_task_group() as tg:
            async with condition:
                assert condition.locked()
                await tg.spawn(notifier)
                await condition.wait()

    async def test_manual_acquire(self):
        async def notifier():
            await condition.acquire()
            try:
                await condition.notify_all()
            finally:
                await condition.release()

        condition = create_condition()
        async with create_task_group() as tg:
            await condition.acquire()
            try:
                assert condition.locked()
                await tg.spawn(notifier)
                await condition.wait()
            finally:
                await condition.release()

    async def test_wait_cancel(self):
        async def task():
            nonlocal task_started, notified
            task_started = True
            async with condition:
                await event.set()
                await condition.wait()
                notified = True

        task_started = notified = False
        event = create_event()
        condition = create_condition()
        async with create_task_group() as tg:
            await tg.spawn(task)
            await event.wait()
            await wait_all_tasks_blocked()
            await tg.cancel_scope.cancel()

        assert task_started
        assert not notified


class TestSemaphore:
    async def test_contextmanager(self):
        async def acquire():
            async with semaphore:
                assert semaphore.value in (0, 1)

        semaphore = create_semaphore(2)
        async with create_task_group() as tg:
            await tg.spawn(acquire, name='task 1')
            await tg.spawn(acquire, name='task 2')

        assert semaphore.value == 2

    async def test_manual_acquire(self):
        async def acquire():
            await semaphore.acquire()
            try:
                assert semaphore.value in (0, 1)
            finally:
                await semaphore.release()

        semaphore = create_semaphore(2)
        async with create_task_group() as tg:
            await tg.spawn(acquire, name='task 1')
            await tg.spawn(acquire, name='task 2')

        assert semaphore.value == 2

    async def test_acquire_cancel(self):
        async def task():
            nonlocal local_scope, acquired
            async with open_cancel_scope() as local_scope, semaphore:
                acquired = True

        local_scope = acquired = None
        semaphore = create_semaphore(1)
        async with create_task_group() as tg:
            async with semaphore:
                await tg.spawn(task)
                await wait_all_tasks_blocked()
                await local_scope.cancel()

        assert not acquired


class TestCapacityLimiter:
    async def test_bad_init_type(self):
        pytest.raises(TypeError, create_capacity_limiter, 1.0).\
            match('total_tokens must be an int or math.inf')

    async def test_bad_init_value(self):
        pytest.raises(ValueError, create_capacity_limiter, 0).\
            match('total_tokens must be >= 1')

    async def test_borrow(self):
        limiter = create_capacity_limiter(2)
        assert limiter.total_tokens == 2
        assert limiter.available_tokens == 2
        assert limiter.borrowed_tokens == 0
        async with limiter:
            assert limiter.total_tokens == 2
            assert limiter.available_tokens == 1
            assert limiter.borrowed_tokens == 1

    async def test_limit(self):
        async def taskfunc():
            nonlocal value
            for _ in range(5):
                async with limiter:
                    assert value == 0
                    value = 1
                    await wait_all_tasks_blocked()
                    value = 0

        value = 0
        limiter = create_capacity_limiter(1)
        async with create_task_group() as tg:
            for _ in range(3):
                await tg.spawn(taskfunc)

    async def test_borrow_twice(self):
        limiter = create_capacity_limiter(1)
        await limiter.acquire()
        with pytest.raises(RuntimeError) as exc:
            await limiter.acquire()

        exc.match("this borrower is already holding one of this CapacityLimiter's tokens")

    async def test_bad_release(self):
        limiter = create_capacity_limiter(1)
        with pytest.raises(RuntimeError) as exc:
            await limiter.release()

        exc.match("this borrower isn't holding any of this CapacityLimiter's tokens")

    async def test_increase_tokens(self):
        async def setter():
            # Wait until waiter() is inside the limiter block
            await event1.wait()
            async with limiter:
                # This can only happen when total_tokens has been increased
                await event2.set()

        async def waiter():
            async with limiter:
                await event1.set()
                await event2.wait()

        limiter = create_capacity_limiter(1)
        event1, event2 = create_event(), create_event()
        async with create_task_group() as tg:
            await tg.spawn(setter)
            await tg.spawn(waiter)
            await wait_all_tasks_blocked()
            assert event1.is_set()
            assert not event2.is_set()
            await limiter.set_total_tokens(2)

        assert event2.is_set()

    async def test_current_default_thread_limiter(self):
        limiter = current_default_worker_thread_limiter()
        assert isinstance(limiter, CapacityLimiter)
        assert limiter.total_tokens == 40
