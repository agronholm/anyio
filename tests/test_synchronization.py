from typing import Optional

import pytest

from anyio import (
    CancelScope, Condition, Event, Lock, Semaphore, WouldBlock, create_task_group, to_thread,
    wait_all_tasks_blocked)
from anyio.abc import CapacityLimiter

pytestmark = pytest.mark.anyio


class TestLock:
    async def test_contextmanager(self) -> None:
        async def task() -> None:
            assert lock.locked()
            async with lock:
                results.append('2')

        results = []
        lock = Lock()
        async with create_task_group() as tg:
            async with lock:
                tg.start_soon(task)
                await wait_all_tasks_blocked()
                results.append('1')

        assert not lock.locked()
        assert results == ['1', '2']

    async def test_manual_acquire(self) -> None:
        async def task() -> None:
            assert lock.locked()
            await lock.acquire()
            try:
                results.append('2')
            finally:
                lock.release()

        results = []
        lock = Lock()
        async with create_task_group() as tg:
            await lock.acquire()
            try:
                tg.start_soon(task)
                await wait_all_tasks_blocked()
                results.append('1')
            finally:
                lock.release()

        assert not lock.locked()
        assert results == ['1', '2']

    async def test_acquire_nowait(self) -> None:
        lock = Lock()
        lock.acquire_nowait()
        assert lock.locked()

    async def test_acquire_nowait_wouldblock(self) -> None:
        async def try_lock() -> None:
            pytest.raises(WouldBlock, lock.acquire_nowait)

        lock = Lock()
        async with lock, create_task_group() as tg:
            assert lock.locked()
            tg.start_soon(try_lock)

    async def test_cancel(self) -> None:
        task_started = got_lock = False

        async def task() -> None:
            nonlocal task_started, got_lock
            task_started = True
            async with lock:
                got_lock = True

        lock = Lock()
        async with create_task_group() as tg:
            async with lock:
                tg.start_soon(task)
                tg.cancel_scope.cancel()

        assert task_started
        assert not got_lock

    async def test_statistics(self) -> None:
        async def waiter() -> None:
            async with lock:
                pass

        lock = Lock()
        async with create_task_group() as tg:
            assert not lock.statistics().locked
            assert lock.statistics().tasks_waiting == 0
            async with lock:
                assert lock.statistics().locked
                assert lock.statistics().tasks_waiting == 0
                for i in range(1, 3):
                    tg.start_soon(waiter)
                    await wait_all_tasks_blocked()
                    assert lock.statistics().tasks_waiting == i

        assert not lock.statistics().locked
        assert lock.statistics().tasks_waiting == 0


class TestEvent:
    async def test_event(self) -> None:
        async def setter() -> None:
            assert not event.is_set()
            event.set()

        event = Event()
        async with create_task_group() as tg:
            tg.start_soon(setter)
            await event.wait()

        assert event.is_set()

    async def test_event_cancel(self) -> None:
        task_started = event_set = False

        async def task() -> None:
            nonlocal task_started, event_set
            task_started = True
            await event.wait()
            event_set = True

        event = Event()
        async with create_task_group() as tg:
            tg.start_soon(task)
            tg.cancel_scope.cancel()
            event.set()

        assert task_started
        assert not event_set

    async def test_statistics(self) -> None:
        async def waiter() -> None:
            await event.wait()

        event = Event()
        async with create_task_group() as tg:
            assert event.statistics().tasks_waiting == 0
            for i in range(1, 3):
                tg.start_soon(waiter)
                await wait_all_tasks_blocked()
                assert event.statistics().tasks_waiting == i

            event.set()

        assert event.statistics().tasks_waiting == 0


class TestCondition:
    async def test_contextmanager(self) -> None:
        async def notifier() -> None:
            async with condition:
                condition.notify_all()

        condition = Condition()
        async with create_task_group() as tg:
            async with condition:
                assert condition.locked()
                tg.start_soon(notifier)
                await condition.wait()

    async def test_manual_acquire(self) -> None:
        async def notifier() -> None:
            await condition.acquire()
            try:
                condition.notify_all()
            finally:
                condition.release()

        condition = Condition()
        async with create_task_group() as tg:
            await condition.acquire()
            try:
                assert condition.locked()
                tg.start_soon(notifier)
                await condition.wait()
            finally:
                condition.release()

    async def test_acquire_nowait(self) -> None:
        condition = Condition()
        condition.acquire_nowait()
        assert condition.locked()

    async def test_acquire_nowait_wouldblock(self) -> None:
        async def try_lock() -> None:
            pytest.raises(WouldBlock, condition.acquire_nowait)

        condition = Condition()
        async with condition, create_task_group() as tg:
            assert condition.locked()
            tg.start_soon(try_lock)

    async def test_wait_cancel(self) -> None:
        task_started = notified = False

        async def task() -> None:
            nonlocal task_started, notified
            task_started = True
            async with condition:
                event.set()
                await condition.wait()
                notified = True

        event = Event()
        condition = Condition()
        async with create_task_group() as tg:
            tg.start_soon(task)
            await event.wait()
            await wait_all_tasks_blocked()
            tg.cancel_scope.cancel()

        assert task_started
        assert not notified

    async def test_statistics(self) -> None:
        async def waiter() -> None:
            async with condition:
                await condition.wait()

        condition = Condition()
        async with create_task_group() as tg:
            assert not condition.statistics().lock_statistics.locked
            assert condition.statistics().tasks_waiting == 0
            async with condition:
                assert condition.statistics().lock_statistics.locked
                assert condition.statistics().tasks_waiting == 0

            for i in range(1, 3):
                tg.start_soon(waiter)
                await wait_all_tasks_blocked()
                assert condition.statistics().tasks_waiting == i

            for i in range(1, -1, -1):
                async with condition:
                    condition.notify(1)

                await wait_all_tasks_blocked()
                assert condition.statistics().tasks_waiting == i

        assert not condition.statistics().lock_statistics.locked
        assert condition.statistics().tasks_waiting == 0


class TestSemaphore:
    async def test_contextmanager(self) -> None:
        async def acquire() -> None:
            async with semaphore:
                assert semaphore.value in (0, 1)

        semaphore = Semaphore(2)
        async with create_task_group() as tg:
            tg.start_soon(acquire, name='task 1')
            tg.start_soon(acquire, name='task 2')

        assert semaphore.value == 2

    async def test_manual_acquire(self) -> None:
        async def acquire() -> None:
            await semaphore.acquire()
            try:
                assert semaphore.value in (0, 1)
            finally:
                semaphore.release()

        semaphore = Semaphore(2)
        async with create_task_group() as tg:
            tg.start_soon(acquire, name='task 1')
            tg.start_soon(acquire, name='task 2')

        assert semaphore.value == 2

    async def test_acquire_nowait(self) -> None:
        semaphore = Semaphore(1)
        semaphore.acquire_nowait()
        assert semaphore.value == 0
        pytest.raises(WouldBlock, semaphore.acquire_nowait)

    async def test_acquire_cancel(self) -> None:
        local_scope = acquired = None

        async def task() -> None:
            nonlocal local_scope, acquired
            with CancelScope() as local_scope:
                async with semaphore:
                    acquired = True

        semaphore = Semaphore(1)
        async with create_task_group() as tg:
            async with semaphore:
                tg.start_soon(task)
                await wait_all_tasks_blocked()
                assert local_scope is not None
                local_scope.cancel()

        assert not acquired

    @pytest.mark.parametrize('max_value', [2, None])
    async def test_max_value(self, max_value: Optional[int]) -> None:
        semaphore = Semaphore(0, max_value=max_value)
        assert semaphore.max_value == max_value

    async def test_max_value_exceeded(self) -> None:
        semaphore = Semaphore(1, max_value=2)
        semaphore.release()
        pytest.raises(ValueError, semaphore.release)

    async def test_statistics(self) -> None:
        async def waiter() -> None:
            async with semaphore:
                pass

        semaphore = Semaphore(1)
        async with create_task_group() as tg:
            assert semaphore.statistics().tasks_waiting == 0
            async with semaphore:
                assert semaphore.statistics().tasks_waiting == 0
                for i in range(1, 3):
                    tg.start_soon(waiter)
                    await wait_all_tasks_blocked()
                    assert semaphore.statistics().tasks_waiting == i

        assert semaphore.statistics().tasks_waiting == 0

    async def test_acquire_race(self) -> None:
        """
        Test against a race condition: when a task waiting on acquire() is rescheduled but another
        task snatches the last available slot, the task should not raise WouldBlock.

        """
        semaphore = Semaphore(1)
        async with create_task_group() as tg:
            semaphore.acquire_nowait()
            tg.start_soon(semaphore.acquire)
            await wait_all_tasks_blocked()
            semaphore.release()
            pytest.raises(WouldBlock, semaphore.acquire_nowait)


class TestCapacityLimiter:
    async def test_bad_init_type(self) -> None:
        pytest.raises(TypeError, CapacityLimiter, 1.0).\
            match('total_tokens must be an int or math.inf')

    async def test_bad_init_value(self) -> None:
        pytest.raises(ValueError, CapacityLimiter, 0).\
            match('total_tokens must be >= 1')

    async def test_borrow(self) -> None:
        limiter = CapacityLimiter(2)
        assert limiter.total_tokens == 2
        assert limiter.available_tokens == 2
        assert limiter.borrowed_tokens == 0
        async with limiter:
            assert limiter.total_tokens == 2
            assert limiter.available_tokens == 1
            assert limiter.borrowed_tokens == 1

    async def test_limit(self) -> None:
        value = 0

        async def taskfunc() -> None:
            nonlocal value
            for _ in range(5):
                async with limiter:
                    assert value == 0
                    value = 1
                    await wait_all_tasks_blocked()
                    value = 0

        limiter = CapacityLimiter(1)
        async with create_task_group() as tg:
            for _ in range(3):
                tg.start_soon(taskfunc)

    async def test_borrow_twice(self) -> None:
        limiter = CapacityLimiter(1)
        await limiter.acquire()
        with pytest.raises(RuntimeError) as exc:
            await limiter.acquire()

        exc.match("this borrower is already holding one of this CapacityLimiter's tokens")

    async def test_bad_release(self) -> None:
        limiter = CapacityLimiter(1)
        with pytest.raises(RuntimeError) as exc:
            limiter.release()

        exc.match("this borrower isn't holding any of this CapacityLimiter's tokens")

    async def test_increase_tokens(self) -> None:
        async def setter() -> None:
            # Wait until waiter() is inside the limiter block
            await event1.wait()
            async with limiter:
                # This can only happen when total_tokens has been increased
                event2.set()

        async def waiter() -> None:
            async with limiter:
                event1.set()
                await event2.wait()

        limiter = CapacityLimiter(1)
        event1, event2 = Event(), Event()
        async with create_task_group() as tg:
            tg.start_soon(setter)
            tg.start_soon(waiter)
            await wait_all_tasks_blocked()
            assert event1.is_set()
            assert not event2.is_set()
            limiter.total_tokens = 2

        assert event2.is_set()

    async def test_current_default_thread_limiter(self) -> None:
        limiter = to_thread.current_default_thread_limiter()
        assert isinstance(limiter, CapacityLimiter)
        assert limiter.total_tokens == 40

    async def test_statistics(self) -> None:
        async def waiter() -> None:
            async with limiter:
                pass

        limiter = CapacityLimiter(1)
        assert limiter.statistics().total_tokens == 1
        assert limiter.statistics().borrowed_tokens == 0
        assert limiter.statistics().tasks_waiting == 0
        async with create_task_group() as tg:
            async with limiter:
                assert limiter.statistics().borrowed_tokens == 1
                assert limiter.statistics().tasks_waiting == 0
                for i in range(1, 3):
                    tg.start_soon(waiter)
                    await wait_all_tasks_blocked()
                    assert limiter.statistics().tasks_waiting == i

        assert limiter.statistics().tasks_waiting == 0
        assert limiter.statistics().borrowed_tokens == 0
