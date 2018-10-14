import pytest

from anyio import (
    create_lock, create_task_group, create_queue, create_event, create_semaphore, create_condition,
    open_cancel_scope, wait_all_tasks_blocked)


class TestLock:
    @pytest.mark.anyio
    async def test_lock(self):
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

    @pytest.mark.anyio
    async def test_lock_cancel(self):
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
    @pytest.mark.anyio
    async def test_event(self):
        async def setter():
            assert not event.is_set()
            await event.set()

        event = create_event()
        async with create_task_group() as tg:
            await tg.spawn(setter)
            await event.wait()
            event.clear()

        assert not event.is_set()

    @pytest.mark.anyio
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
    @pytest.mark.anyio
    async def test_condition(self):
        async def notifier():
            async with condition:
                await condition.notify_all()

        condition = create_condition()
        async with create_task_group() as tg:
            async with condition:
                assert condition.locked()
                await tg.spawn(notifier)
                await condition.wait()

    @pytest.mark.anyio
    async def test_wait_cancel(self):
        async def task():
            nonlocal task_started, notified
            task_started = True
            async with condition:
                await event.set()
                event.clear()
                await event.wait()
                await condition.wait()
                notified = True

        task_started = notified = False
        event = create_event()
        condition = create_condition()
        async with create_task_group() as tg:
            await tg.spawn(task)
            await event.wait()
            await tg.cancel_scope.cancel()
            await event.set()

        assert task_started
        assert not notified


class TestSemaphore:
    @pytest.mark.anyio
    async def test_semaphore(self):
        async def acquire():
            async with semaphore:
                assert semaphore.value in (0, 1)

        semaphore = create_semaphore(2)
        async with create_task_group() as tg:
            await tg.spawn(acquire, name='task 1')
            await tg.spawn(acquire, name='task 2')

        assert semaphore.value == 2

    @pytest.mark.anyio
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


class TestQueue:
    @pytest.mark.anyio
    async def test_queue(self):
        queue = create_queue(1)
        assert queue.empty()
        await queue.put('1')
        assert queue.full()
        assert queue.qsize() == 1
        assert await queue.get() == '1'
        assert queue.empty()

    @pytest.mark.anyio
    async def test_get_cancel(self):
        async def task():
            nonlocal local_scope
            async with open_cancel_scope() as local_scope:
                await queue.get()

        local_scope = None
        queue = create_queue(1)
        async with create_task_group() as tg:
            await tg.spawn(task)
            await wait_all_tasks_blocked()
            await local_scope.cancel()
            await queue.put(None)

        assert queue.full()

    @pytest.mark.anyio
    async def test_put_cancel(self):
        async def task():
            nonlocal local_scope
            async with open_cancel_scope() as local_scope:
                await queue.put(None)

        local_scope = None
        queue = create_queue(1)
        await queue.put(None)
        async with create_task_group() as tg:
            await tg.spawn(task)
            await wait_all_tasks_blocked()
            await local_scope.cancel()
            await queue.get()

        assert queue.empty()
