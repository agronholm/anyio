import threading

import pytest

from anyio import run_async_from_thread, run_in_thread, create_task_group, sleep


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


def test_run_async_from_unclaimed_thread():
    async def foo():
        pass

    exc = pytest.raises(RuntimeError, run_async_from_thread, foo)
    exc.match('This function can only be run from an AnyIO worker thread')
