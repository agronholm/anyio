import curio
import pytest
import trio

from anyio import (
    create_task_group, sleep, move_on_after, fail_after, open_cancel_scope, wait_all_tasks_blocked,
    current_effective_deadline, current_time, get_cancelled_exc_class)
from anyio._backends import _asyncio
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
    (_asyncio.native_run, True),
    (curio.run, False),
    (trio.run, False)
], ids=['asyncio', 'curio', 'trio'])
def test_run_natively(run_func, as_coro_obj):
    async def testfunc():
        async with create_task_group() as tg:
            await tg.spawn(sleep, 0)

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
        assert marker is None
        await tg.cancel_scope.cancel()

    assert marker == 1


@pytest.mark.anyio
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


@pytest.mark.anyio
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
async def test_cancel_propagation():
    async def g():
        async with create_task_group():
            await sleep(1)

        assert False

    async with create_task_group() as group:
        await group.spawn(g)
        await sleep(0)
        await group.cancel_scope.cancel()


@pytest.mark.anyio
async def test_multi_error_children():
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            await tg.spawn(async_error, 'task1')
            await tg.spawn(async_error, 'task2')

    assert len(exc.value.exceptions) == 2
    assert sorted(str(e) for e in exc.value.exceptions) == ['task1', 'task2']
    assert exc.match('^2 exceptions were raised in the task group:\n')
    assert exc.match(r'Exception: task\d\n----')


@pytest.mark.anyio
async def test_multi_error_host():
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            await tg.spawn(async_error, 'child', 2)
            await wait_all_tasks_blocked()
            raise Exception('host')

    assert len(exc.value.exceptions) == 2
    assert [str(e) for e in exc.value.exceptions] == ['host', 'child']
    assert exc.match('^2 exceptions were raised in the task group:\n')
    assert exc.match(r'Exception: host\n----')


@pytest.mark.anyio
async def test_escaping_cancelled_exception():
    async with create_task_group() as tg:
        await tg.cancel_scope.cancel()
        await sleep(0)


@pytest.mark.anyio
async def test_cancel_scope_cleared():
    async with move_on_after(0.1):
        await sleep(1)

    await sleep(0)


@pytest.mark.anyio
async def test_fail_after():
    with pytest.raises(TimeoutError):
        async with fail_after(0.1) as scope:
            await sleep(1)

    assert scope.cancel_called


@pytest.mark.anyio
async def test_fail_after_no_timeout():
    async with fail_after(None) as scope:
        assert scope.deadline == float('inf')
        await sleep(0.1)

    assert not scope.cancel_called


@pytest.mark.anyio
async def test_move_on_after():
    result = False
    async with move_on_after(0.1) as scope:
        await sleep(1)
        result = True

    assert not result
    assert scope.cancel_called


@pytest.mark.anyio
async def test_move_on_after_no_timeout():
    result = False
    async with move_on_after(None) as scope:
        assert scope.deadline == float('inf')
        await sleep(0.1)
        result = True

    assert result
    assert not scope.cancel_called


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_cancel_cascade():
    async def do_something():
        async with create_task_group() as task_group:
            await task_group.spawn(sleep, 1)

        raise Exception('foo')

    async with create_task_group() as tg:
        await tg.spawn(do_something)
        await wait_all_tasks_blocked()
        await tg.cancel_scope.cancel()


@pytest.mark.anyio
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


@pytest.mark.anyio
async def test_shielded_deadline():
    async with move_on_after(10):
        async with open_cancel_scope(shield=True):
            async with move_on_after(1000):
                assert await current_effective_deadline() - await current_time() > 900


@pytest.mark.anyio
async def test_deadline_reached_on_start():
    async with move_on_after(0):
        await sleep(0)
        pytest.fail('Execution should not reach this point')


@pytest.mark.anyio
async def test_timeout_error_with_multiple_cancellations():
    with pytest.raises(TimeoutError):
        async with fail_after(0.1):
            async with create_task_group() as tg:
                await tg.spawn(sleep, 2)
                await sleep(2)


@pytest.mark.anyio
async def test_catch_cancellation():
    finalizer_done = False
    async with move_on_after(0.1):
        try:
            await sleep(1)
        except get_cancelled_exc_class():
            finalizer_done = True
            raise

    assert finalizer_done


@pytest.mark.anyio
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


@pytest.mark.anyio
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
