import curio
import pytest
import trio

from anyio import (
    create_task_group, sleep, move_on_after, fail_after, open_cancel_scope,
    reset_detected_asynclib)
from anyio._backends import asyncio
from anyio.exceptions import ExceptionGroup


async def async_error(text, delay=0.1):
    try:
        if delay:
            await sleep(delay)
    finally:
        raise Exception(text)


@pytest.mark.anyio
async def test_already_closed():
    async with create_task_group() as tg:
        pass

    with pytest.raises(RuntimeError) as exc:
        await tg.spawn(async_error, 'fail')

    exc.match('This task group is not active; no new tasks can be spawned')


@pytest.mark.anyio
async def test_success():
    async def async_add(value):
        results.add(value)

    results = set()
    async with create_task_group() as tg:
        await tg.spawn(async_add, 'a')
        await tg.spawn(async_add, 'b')

    assert results == {'a', 'b'}


@pytest.mark.parametrize('run_func, as_coro_obj', [
    (asyncio.native_run, True),
    (curio.run, False),
    (trio.run, False)
], ids=['asyncio', 'curio', 'trio'])
def test_run_natively(run_func, as_coro_obj):
    async def testfunc():
        async with create_task_group() as tg:
            await tg.spawn(sleep, 0)

    reset_detected_asynclib()
    if as_coro_obj:
        run_func(testfunc())
    else:
        run_func(testfunc)


@pytest.mark.anyio
async def test_spawn_while_running():
    async def task_func():
        await tg.spawn(sleep, 0)

    async with create_task_group() as tg:
        await tg.spawn(task_func)


@pytest.mark.anyio
async def test_spawn_after_error():
    with pytest.raises(ZeroDivisionError):
        async with create_task_group() as tg:
            a = 1 / 0  # noqa: F841

    with pytest.raises(RuntimeError) as exc:
        await tg.spawn(sleep, 0)

    exc.match('This task group is not active; no new tasks can be spawned')


@pytest.mark.anyio
async def test_host_exception():
    async def set_result(value):
        nonlocal result
        await sleep(3)
        result = value

    result = None
    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            await tg.spawn(set_result, 'a')
            raise Exception('dummy error')

    exc.match('dummy error')
    assert result is None


@pytest.mark.anyio
async def test_edge_cancellation():
    async def dummy():
        nonlocal marker
        marker = 1
        # At this point the task has been cancelled so sleep() will raise an exception
        await sleep(0)
        # Execution should never get this far
        marker = 2

    marker = None
    async with create_task_group() as tg:
        await tg.spawn(dummy)
        await tg.cancel_scope.cancel()

    assert marker == 1


# @pytest.mark.anyio
# async def test_host_cancelled_before_aexit():
#     async def set_result(value):
#         nonlocal result
#         await sleep(3)
#         result = value
#
#     async def host():
#         async with create_task_group() as tg:
#             await tg.spawn(set_result, 'a')
#
#     result = None
#     with pytest.raises(event_loop.CancelledError):
#         with open_cancel_scope() as scope:
#             async with create_task_group() as main_group:
#                 await main_group.spawn(host)
#                 await sleep(0.1)
#                 scope.cancel()
#
#     assert result is None


# @pytest.mark.anyio
# async def test_host_cancelled_during_aexit(event_loop, queue):
#     with pytest.raises(CancelledError):
#         async with event_loop.TaskGroup() as tg:
#             tg.spawn(self.delayed_put, event_loop, queue, 'a')
#             event_loop.call_soon(asyncio.Task.current_task().cancel)
#
#     assert queue.empty()


@pytest.mark.anyio
async def test_cancel_scope_in_another_task():
    async def child():
        nonlocal result, local_scope
        async with open_cancel_scope() as local_scope:
            await sleep(2)
            result = True

    local_scope = None
    result = False
    async with create_task_group() as tg:
        await tg.spawn(child)
        while local_scope is None:
            await sleep(0)

        await local_scope.cancel()

    assert not result


@pytest.mark.anyio
async def test_multi_error_children():
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            await tg.spawn(async_error, 'task1')
            await tg.spawn(async_error, 'task2')

    assert len(exc.value.exceptions) == 2
    assert sorted(str(e) for e in exc.value.exceptions) == ['task1', 'task2']


@pytest.mark.anyio
async def test_multi_error_host():
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            await tg.spawn(async_error, 'child', 2)
            await sleep(0.1)
            raise Exception('host')

    assert len(exc.value.exceptions) == 2
    assert [str(e) for e in exc.value.exceptions] == ['host', 'child']


@pytest.mark.anyio
async def test_escaping_cancelled_exception():
    async with create_task_group() as tg:
        await tg.cancel_scope.cancel()
        await sleep(0)


@pytest.mark.anyio
async def test_fail_after():
    with pytest.raises(TimeoutError):
        async with fail_after(0.1):
            await sleep(1)


@pytest.mark.anyio
async def test_fail_after_no_timeout():
    async with fail_after(None):
        await sleep(0.1)


@pytest.mark.anyio
async def test_move_on_after():
    result = False
    async with move_on_after(0.1):
        await sleep(1)
        result = True

    assert not result


@pytest.mark.anyio
async def test_move_on_after_no_timeout():
    result = False
    async with move_on_after(None):
        await sleep(0.1)
        result = True

    assert result
