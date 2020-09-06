import asyncio
import sys

import curio
import pytest
import trio

import anyio
from anyio import (
    ExceptionGroup, create_task_group, current_effective_deadline, current_time, fail_after,
    move_on_after, open_cancel_scope, sleep, wait_all_tasks_blocked)

pytestmark = pytest.mark.anyio


async def async_error(text, delay=0.1):
    try:
        if delay:
            await sleep(delay)
    finally:
        raise Exception(text)


async def test_already_closed():
    async with create_task_group() as tg:
        pass

    with pytest.raises(RuntimeError) as exc:
        await tg.spawn(async_error, 'fail')

    exc.match('This task group is not active; no new tasks can be spawned')


async def test_success():
    async def async_add(value):
        results.add(value)

    results = set()
    async with create_task_group() as tg:
        await tg.spawn(async_add, 'a')
        await tg.spawn(async_add, 'b')

    assert results == {'a', 'b'}


@pytest.mark.parametrize('module', [
    pytest.param(asyncio, id='asyncio'),
    pytest.param(curio, id='curio'),
    pytest.param(trio, id='trio')
])
def test_run_natively(module):
    async def testfunc():
        async with create_task_group() as tg:
            await tg.spawn(sleep, 0)

    if module is asyncio:
        from anyio._backends._asyncio import native_run
        try:
            native_run(testfunc())
        finally:
            asyncio.set_event_loop(asyncio.new_event_loop())
    else:
        module.run(testfunc)


async def test_spawn_while_running():
    async def task_func():
        await tg.spawn(sleep, 0)

    async with create_task_group() as tg:
        await tg.spawn(task_func)


async def test_spawn_after_error():
    with pytest.raises(ZeroDivisionError):
        async with create_task_group() as tg:
            a = 1 / 0  # noqa: F841

    with pytest.raises(RuntimeError) as exc:
        await tg.spawn(sleep, 0)

    exc.match('This task group is not active; no new tasks can be spawned')


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
        assert marker is None
        await tg.cancel_scope.cancel()

    assert marker == 1


async def test_failing_child_task_cancels_host():
    async def child():
        await wait_all_tasks_blocked()
        raise Exception('foo')

    sleep_completed = False
    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            await tg.spawn(child)
            await sleep(0.5)
            sleep_completed = True

    exc.match('foo')
    assert not sleep_completed


async def test_failing_host_task_cancels_children():
    async def child():
        nonlocal sleep_completed
        await sleep(1)
        sleep_completed = True

    sleep_completed = False
    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            await tg.spawn(child)
            await wait_all_tasks_blocked()
            raise Exception('foo')

    exc.match('foo')
    assert not sleep_completed


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


async def test_cancel_propagation():
    async def g():
        async with create_task_group():
            await sleep(1)

        assert False

    async with create_task_group() as group:
        await group.spawn(g)
        await sleep(0)
        await group.cancel_scope.cancel()


async def test_cancel_twice():
    """
    Test that the same task can receive two cancellations. This is mostly to test the workaround
    for curio's philosophy that a task should not be cancelled twice.

    """
    async def cancel_group():
        await wait_all_tasks_blocked()
        await group.cancel_scope.cancel()

    for _ in range(2):
        async with create_task_group() as group:
            await group.spawn(cancel_group)
            await sleep(1)
            pytest.fail('Execution should not reach this point')


async def test_cancel_exiting_task_group():
    """
    Test that if a task group is waiting for subtasks to finish and it receives a cancellation, the
    subtasks are also cancelled and the waiting continues.

    """
    async def waiter():
        nonlocal cancel_received
        try:
            await sleep(5)
        finally:
            cancel_received = True

    async def subgroup():
        async with create_task_group() as tg2:
            await tg2.spawn(waiter)

    cancel_received = False
    async with create_task_group() as tg:
        await tg.spawn(subgroup)
        await wait_all_tasks_blocked()
        await tg.cancel_scope.cancel()

    assert cancel_received


async def test_exception_group_children():
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            await tg.spawn(async_error, 'task1')
            await tg.spawn(async_error, 'task2', 0.15)

    assert len(exc.value.exceptions) == 2
    assert sorted(str(e) for e in exc.value.exceptions) == ['task1', 'task2']
    assert exc.match('^2 exceptions were raised in the task group:\n')
    assert exc.match(r'Exception: task\d\n----')
    if sys.version_info < (3, 7):
        assert repr(exc.value) == "<ExceptionGroup: Exception('task1',), Exception('task2',)>"
    else:
        assert repr(exc.value) == "<ExceptionGroup: Exception('task1'), Exception('task2')>"


async def test_exception_group_host():
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            await tg.spawn(async_error, 'child', 2)
            await wait_all_tasks_blocked()
            raise Exception('host')

    assert len(exc.value.exceptions) == 2
    assert [str(e) for e in exc.value.exceptions] == ['host', 'child']
    assert exc.match('^2 exceptions were raised in the task group:\n')
    assert exc.match(r'Exception: host\n----')


async def test_escaping_cancelled_exception():
    async with create_task_group() as tg:
        await tg.cancel_scope.cancel()
        await sleep(0)


async def test_cancel_scope_cleared():
    async with move_on_after(0.1):
        await sleep(1)

    await sleep(0)


@pytest.mark.parametrize('delay', [0, 0.1], ids=['instant', 'delayed'])
async def test_fail_after(delay):
    with pytest.raises(TimeoutError):
        async with fail_after(delay) as scope:
            await sleep(1)

    assert scope.cancel_called


async def test_fail_after_no_timeout():
    async with fail_after(None) as scope:
        assert scope.deadline == float('inf')
        await sleep(0.1)

    assert not scope.cancel_called


async def test_fail_after_after_cancellation():
    event = anyio.create_event()
    async with anyio.create_task_group() as tg:
        await tg.spawn(tg.cancel_scope.cancel)
        await event.wait()

    block_complete = False
    with pytest.raises(TimeoutError):
        async with anyio.fail_after(0.1):
            await anyio.sleep(0.5)
            block_complete = True

    assert not block_complete


@pytest.mark.parametrize('delay', [0, 0.1], ids=['instant', 'delayed'])
async def test_move_on_after(delay):
    result = False
    async with move_on_after(delay) as scope:
        await sleep(1)
        result = True

    assert not result
    assert scope.cancel_called


async def test_move_on_after_no_timeout():
    result = False
    async with move_on_after(None) as scope:
        assert scope.deadline == float('inf')
        await sleep(0.1)
        result = True

    assert result
    assert not scope.cancel_called


async def test_nested_move_on_after():
    sleep_completed = inner_scope_completed = False
    async with move_on_after(0.1) as outer_scope:
        assert await current_effective_deadline() == outer_scope.deadline
        async with move_on_after(1) as inner_scope:
            assert await current_effective_deadline() == outer_scope.deadline
            await sleep(2)
            sleep_completed = True

        inner_scope_completed = True

    assert not sleep_completed
    assert not inner_scope_completed
    assert outer_scope.cancel_called
    assert not inner_scope.cancel_called


async def test_shielding():
    async def cancel_when_ready():
        await wait_all_tasks_blocked()
        await tg.cancel_scope.cancel()

    inner_sleep_completed = outer_sleep_completed = False
    async with create_task_group() as tg:
        await tg.spawn(cancel_when_ready)
        async with move_on_after(10, shield=True) as inner_scope:
            assert inner_scope.shield
            await sleep(0.1)
            inner_sleep_completed = True

        await sleep(1)
        outer_sleep_completed = True

    assert inner_sleep_completed
    assert not outer_sleep_completed
    assert tg.cancel_scope.cancel_called
    assert not inner_scope.cancel_called


async def test_shielding_immediate_scope_cancelled():
    async def cancel_when_ready():
        await wait_all_tasks_blocked()
        await scope.cancel()

    sleep_completed = False
    async with create_task_group() as tg:
        async with open_cancel_scope(shield=True) as scope:
            await tg.spawn(cancel_when_ready)
            await sleep(0.5)
            sleep_completed = True

    assert not sleep_completed


async def test_cancel_scope_in_child_task():
    async def child():
        nonlocal child_scope
        async with open_cancel_scope() as child_scope:
            await sleep(2)

    child_scope = None
    host_done = False
    async with create_task_group() as tg:
        await tg.spawn(child)
        await wait_all_tasks_blocked()
        await child_scope.cancel()
        await sleep(0.1)
        host_done = True

    assert host_done
    assert not tg.cancel_scope.cancel_called


async def test_exception_cancels_siblings():
    async def child(fail):
        if fail:
            raise Exception('foo')
        else:
            nonlocal sleep_completed
            await sleep(1)
            sleep_completed = True

    sleep_completed = False
    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            await tg.spawn(child, False)
            await wait_all_tasks_blocked()
            await tg.spawn(child, True)

    exc.match('foo')
    assert not sleep_completed


async def test_cancel_cascade():
    async def do_something():
        async with create_task_group() as task_group:
            await task_group.spawn(sleep, 1)

        raise Exception('foo')

    async with create_task_group() as tg:
        await tg.spawn(do_something)
        await wait_all_tasks_blocked()
        await tg.cancel_scope.cancel()


async def test_cancelled_parent():
    async def child():
        async with open_cancel_scope():
            await sleep(1)

        raise Exception('foo')

    async def parent(tg):
        await wait_all_tasks_blocked()
        await tg.spawn(child)

    async with create_task_group() as tg:
        await tg.spawn(parent, tg)
        await tg.cancel_scope.cancel()


async def test_shielded_deadline():
    async with move_on_after(10):
        async with open_cancel_scope(shield=True):
            async with move_on_after(1000):
                assert await current_effective_deadline() - await current_time() > 900


async def test_deadline_reached_on_start():
    async with move_on_after(0):
        await sleep(0)
        pytest.fail('Execution should not reach this point')


async def test_timeout_error_with_multiple_cancellations():
    with pytest.raises(TimeoutError):
        async with fail_after(0.1):
            async with create_task_group() as tg:
                await tg.spawn(sleep, 2)
                await sleep(2)


async def test_nested_fail_after():
    async def killer(scope):
        await wait_all_tasks_blocked()
        await scope.cancel()

    async with create_task_group() as tg:
        async with open_cancel_scope() as scope:
            async with open_cancel_scope():
                await tg.spawn(killer, scope)
                async with fail_after(1):
                    await sleep(2)
                    pytest.fail('Execution should not reach this point')

                pytest.fail('Execution should not reach this point either')

            pytest.fail('Execution should also not reach this point')

    assert scope.cancel_called


async def test_nested_shield():
    async def killer(scope):
        await wait_all_tasks_blocked()
        await scope.cancel()

    with pytest.raises(TimeoutError):
        async with create_task_group() as tg:
            async with open_cancel_scope() as scope:
                async with open_cancel_scope(shield=True):
                    await tg.spawn(killer, scope)
                    async with fail_after(0.2):
                        await sleep(2)


def test_task_group_in_generator(anyio_backend_name, anyio_backend_options):
    async def task_group_generator():
        async with create_task_group():
            yield

    gen = task_group_generator()
    anyio.run(gen.__anext__, backend=anyio_backend_name, backend_options=anyio_backend_options)
    pytest.raises(StopAsyncIteration, anyio.run, gen.__anext__, backend=anyio_backend_name,
                  backend_options=anyio_backend_options)


async def test_exception_group_filtering():
    """Test that CancelledErrors are filtered out of nested exception groups."""

    async def fail(name):
        try:
            await anyio.sleep(.1)
        finally:
            raise Exception('%s task failed' % name)

    async def fn():
        async with anyio.create_task_group() as task_group:
            await task_group.spawn(fail, 'parent')
            async with anyio.create_task_group() as task_group2:
                await task_group2.spawn(fail, 'child')
                await anyio.sleep(1)

    with pytest.raises(ExceptionGroup) as exc:
        await fn()

    assert len(exc.value.exceptions) == 2
    assert str(exc.value.exceptions[0]) == 'parent task failed'
    assert str(exc.value.exceptions[1]) == 'child task failed'


async def test_cancel_propagation_with_inner_spawn():
    async def g():
        async with anyio.create_task_group() as g:
            await g.spawn(anyio.sleep, 10)
            await anyio.sleep(5)

        assert False

    async with anyio.create_task_group() as group:
        await group.spawn(g)
        await anyio.sleep(0.1)
        await group.cancel_scope.cancel()


async def test_escaping_cancelled_error_from_cancelled_task():
    """Regression test for issue #88. No CancelledError should escape the outer scope."""
    async with open_cancel_scope() as scope:
        async with move_on_after(0.1):
            await sleep(1)

        await scope.cancel()


@pytest.mark.filterwarnings('ignore:"@coroutine" decorator is deprecated:DeprecationWarning')
def test_cancel_generator_based_task():
    from asyncio import coroutine

    async def native_coro_part():
        async with open_cancel_scope() as scope:
            await scope.cancel()

    @coroutine
    def generator_part():
        yield from native_coro_part()

    anyio.run(generator_part, backend='asyncio')


async def test_suppress_exception_context():
    """
    Test that the __context__ attribute has been cleared when the exception is re-raised in the
    exception group. This prevents recursive tracebacks.

    """
    with pytest.raises(ValueError) as exc:
        async with create_task_group() as tg:
            await tg.cancel_scope.cancel()
            async with create_task_group() as inner:
                await inner.spawn(sleep, 1)
                raise ValueError

    assert exc.value.__context__ is None
