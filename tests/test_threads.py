import pytest

from anyio import (
    run_async_from_thread, run_in_thread, is_in_event_loop_thread, create_task_group)


@pytest.mark.anyio
async def test_run_async_from_thread():
    async def add(a, b):
        assert is_in_event_loop_thread()
        return a + b

    def worker(a, b):
        assert not is_in_event_loop_thread()
        return run_async_from_thread(add, a, b)

    result = await run_in_thread(worker, 1, 2)
    assert result == 3


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
