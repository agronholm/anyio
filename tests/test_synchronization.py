from __future__ import annotations

import asyncio
from typing import Any

import pytest

from anyio import (
    CancelScope,
    Condition,
    Event,
    Lock,
    Semaphore,
    WouldBlock,
    create_task_group,
    fail_after,
    run,
    to_thread,
    wait_all_tasks_blocked,
)
from anyio.abc import CapacityLimiter, TaskStatus

pytestmark = pytest.mark.anyio


class TestLock:
    async def test_contextmanager(self) -> None:
        async def task() -> None:
            assert lock.locked()
            async with lock:
                results.append("2")

        results = []
        lock = Lock()
        async with create_task_group() as tg:
            async with lock:
                tg.start_soon(task)
                await wait_all_tasks_blocked()
                results.append("1")

        assert not lock.locked()
        assert results == ["1", "2"]

    async def test_manual_acquire(self) -> None:
        async def task() -> None:
            assert lock.locked()
            await lock.acquire()
            try:
                results.append("2")
            finally:
                lock.release()

        results = []
        lock = Lock()
        async with create_task_group() as tg:
            await lock.acquire()
            try:
                tg.start_soon(task)
                await wait_all_tasks_blocked()
                results.append("1")
            finally:
                lock.release()

        assert not lock.locked()
        assert results == ["1", "2"]

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

    @pytest.mark.parametrize(
        "release_first",
        [pytest.param(False, id="releaselast"), pytest.param(True, id="releasefirst")],
    )
    async def test_cancel_during_acquire(self, release_first: bool) -> None:
        acquired = False

        async def task(*, task_status: TaskStatus) -> None:
            nonlocal acquired
            task_status.started()
            async with lock:
                acquired = True

        lock = Lock()
        async with create_task_group() as tg:
            await lock.acquire()
            await tg.start(task)
            tg.cancel_scope.cancel()
            with CancelScope(shield=True):
                if release_first:
                    lock.release()
                    await wait_all_tasks_blocked()
                else:
                    await wait_all_tasks_blocked()
                    lock.release()

        assert not acquired
        assert not lock.locked()

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

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    async def test_asyncio_deadlock(self) -> None:
        """Regression test for #398."""
        lock = Lock()

        async def acquire() -> None:
            async with lock:
                await asyncio.sleep(0)

        loop = asyncio.get_running_loop()
        task1 = loop.create_task(acquire())
        task2 = loop.create_task(acquire())
        await asyncio.sleep(0)
        task1.cancel()
        await asyncio.wait_for(task2, 1)

    def test_instantiate_outside_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def use_lock() -> None:
            async with lock:
                pass

        lock = Lock()
        statistics = lock.statistics()
        assert not statistics.locked
        assert statistics.owner is None
        assert statistics.tasks_waiting == 0

        run(use_lock, backend=anyio_backend_name, backend_options=anyio_backend_options)


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

    async def test_event_wait_before_set_before_cancel(self) -> None:
        setter_started = waiter_woke = False

        async def setter() -> None:
            nonlocal setter_started
            setter_started = True
            assert not event.is_set()
            event.set()
            tg.cancel_scope.cancel()

        event = Event()
        async with create_task_group() as tg:
            tg.start_soon(setter)
            await event.wait()
            waiter_woke = True

        assert setter_started
        assert waiter_woke

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

    def test_instantiate_outside_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def use_event() -> None:
            event.set()
            await event.wait()

        event = Event()
        assert not event.is_set()
        assert event.statistics().tasks_waiting == 0

        run(
            use_event, backend=anyio_backend_name, backend_options=anyio_backend_options
        )


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

    def test_instantiate_outside_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def use_condition() -> None:
            async with condition:
                pass

        condition = Condition()
        assert condition.statistics().tasks_waiting == 0

        run(
            use_condition,
            backend=anyio_backend_name,
            backend_options=anyio_backend_options,
        )


class TestSemaphore:
    async def test_contextmanager(self) -> None:
        async def acquire() -> None:
            async with semaphore:
                assert semaphore.value in (0, 1)

        semaphore = Semaphore(2)
        async with create_task_group() as tg:
            tg.start_soon(acquire, name="task 1")
            tg.start_soon(acquire, name="task 2")

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
            tg.start_soon(acquire, name="task 1")
            tg.start_soon(acquire, name="task 2")

        assert semaphore.value == 2

    async def test_acquire_nowait(self) -> None:
        semaphore = Semaphore(1)
        semaphore.acquire_nowait()
        assert semaphore.value == 0
        pytest.raises(WouldBlock, semaphore.acquire_nowait)

    @pytest.mark.parametrize(
        "release_first",
        [pytest.param(False, id="releaselast"), pytest.param(True, id="releasefirst")],
    )
    async def test_cancel_during_acquire(self, release_first: bool) -> None:
        acquired = False

        async def task(*, task_status: TaskStatus) -> None:
            nonlocal acquired
            task_status.started()
            async with semaphore:
                acquired = True

        semaphore = Semaphore(1)
        async with create_task_group() as tg:
            await semaphore.acquire()
            await tg.start(task)
            tg.cancel_scope.cancel()
            with CancelScope(shield=True):
                if release_first:
                    semaphore.release()
                    await wait_all_tasks_blocked()
                else:
                    await wait_all_tasks_blocked()
                    semaphore.release()

        assert not acquired
        assert semaphore.value == 1

    @pytest.mark.parametrize("max_value", [2, None])
    async def test_max_value(self, max_value: int | None) -> None:
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
        Test against a race condition: when a task waiting on acquire() is rescheduled
        but another task snatches the last available slot, the task should not raise
        WouldBlock.

        """
        semaphore = Semaphore(1)
        async with create_task_group() as tg:
            semaphore.acquire_nowait()
            tg.start_soon(semaphore.acquire)
            await wait_all_tasks_blocked()
            semaphore.release()
            pytest.raises(WouldBlock, semaphore.acquire_nowait)

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    async def test_asyncio_deadlock(self) -> None:
        """Regression test for #398."""
        semaphore = Semaphore(1)

        async def acquire() -> None:
            async with semaphore:
                await asyncio.sleep(0)

        loop = asyncio.get_running_loop()
        task1 = loop.create_task(acquire())
        task2 = loop.create_task(acquire())
        await asyncio.sleep(0)
        task1.cancel()
        await asyncio.wait_for(task2, 1)

    def test_instantiate_outside_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def use_semaphore() -> None:
            async with semaphore:
                pass

        semaphore = Semaphore(1)
        assert semaphore.statistics().tasks_waiting == 0

        run(
            use_semaphore,
            backend=anyio_backend_name,
            backend_options=anyio_backend_options,
        )


class TestCapacityLimiter:
    async def test_bad_init_type(self) -> None:
        pytest.raises(TypeError, CapacityLimiter, 1.0).match(
            "total_tokens must be an int or math.inf"
        )

    async def test_bad_init_value(self) -> None:
        pytest.raises(ValueError, CapacityLimiter, 0).match("total_tokens must be >= 1")

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

        exc.match(
            "this borrower is already holding one of this CapacityLimiter's tokens"
        )

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

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    async def test_asyncio_deadlock(self) -> None:
        """Regression test for #398."""
        limiter = CapacityLimiter(1)

        async def acquire() -> None:
            async with limiter:
                await asyncio.sleep(0)

        loop = asyncio.get_running_loop()
        task1 = loop.create_task(acquire())
        task2 = loop.create_task(acquire())
        await asyncio.sleep(0)
        task1.cancel()
        await asyncio.wait_for(task2, 1)

    async def test_ordered_queue(self) -> None:
        limiter = CapacityLimiter(1)
        results = []
        event = Event()

        async def append(x: int, task_status: TaskStatus) -> None:
            task_status.started()
            async with limiter:
                await event.wait()
                results.append(x)

        async with create_task_group() as tg:
            for i in [0, 1, 2]:
                await tg.start(append, i)

            event.set()

        assert results == [0, 1, 2]

    async def test_increase_tokens_lets_others_acquire(self) -> None:
        limiter = CapacityLimiter(1)
        entered_events = [Event() for _ in range(3)]
        continue_event = Event()

        async def worker(entered_event: Event) -> None:
            async with limiter:
                entered_event.set()
                await continue_event.wait()

        async with create_task_group() as tg:
            for event in entered_events[:2]:
                tg.start_soon(worker, event)

            # One task should be able to acquire the limiter while the other is left
            # waiting
            await wait_all_tasks_blocked()
            assert sum(ev.is_set() for ev in entered_events) == 1

            # Increase the total tokens and start another worker.
            # All tasks should be able to acquire the limiter now.
            limiter.total_tokens = 3
            tg.start_soon(worker, entered_events[2])
            with fail_after(1):
                for ev in entered_events[1:]:
                    await ev.wait()

            # Allow all tasks to exit
            continue_event.set()

    def test_instantiate_outside_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def use_limiter() -> None:
            async with limiter:
                pass

        limiter = CapacityLimiter(1)
        limiter.total_tokens = 2

        with pytest.raises(TypeError):
            limiter.total_tokens = "2"  # type: ignore[assignment]

        with pytest.raises(TypeError):
            limiter.total_tokens = 3.0

        assert limiter.total_tokens == 2
        assert limiter.borrowed_tokens == 0
        statistics = limiter.statistics()
        assert statistics.total_tokens == 2
        assert statistics.borrowed_tokens == 0
        assert statistics.borrowers == ()
        assert statistics.tasks_waiting == 0

        run(
            use_limiter,
            backend=anyio_backend_name,
            backend_options=anyio_backend_options,
        )

    async def test_total_tokens_as_kwarg(self) -> None:
        # Regression test for #515
        limiter = CapacityLimiter(total_tokens=1)
        assert limiter.total_tokens == 1
