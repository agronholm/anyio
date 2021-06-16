import asyncio
import re
import sys
import time
from typing import Any, AsyncGenerator, Coroutine, Dict, Generator, NoReturn, Set

import pytest
import trio

import anyio
from anyio import (
    CancelScope, ExceptionGroup, create_task_group, current_effective_deadline, current_time,
    fail_after, get_cancelled_exc_class, move_on_after, sleep, wait_all_tasks_blocked)
from anyio.abc import TaskGroup, TaskStatus

if sys.version_info < (3, 7):
    current_task = asyncio.Task.current_task
else:
    current_task = asyncio.current_task

pytestmark = pytest.mark.anyio


async def async_error(text: str, delay: float = 0.1) -> NoReturn:
    try:
        if delay:
            await sleep(delay)
    finally:
        raise Exception(text)


async def test_already_closed() -> None:
    async with create_task_group() as tg:
        pass

    with pytest.raises(RuntimeError) as exc:
        tg.start_soon(async_error, 'fail')

    exc.match('This task group is not active; no new tasks can be started')


async def test_success() -> None:
    async def async_add(value: str) -> None:
        results.add(value)

    results: Set[str] = set()
    async with create_task_group() as tg:
        tg.start_soon(async_add, 'a')
        tg.start_soon(async_add, 'b')

    assert results == {'a', 'b'}


@pytest.mark.parametrize('module', [
    pytest.param(asyncio, id='asyncio'),
    pytest.param(trio, id='trio')
])
def test_run_natively(module: Any) -> None:
    async def testfunc() -> None:
        async with create_task_group() as tg:
            tg.start_soon(sleep, 0)

    if module is asyncio:
        from anyio._backends._asyncio import native_run  # type: ignore[attr-defined]
        try:
            native_run(testfunc())
        finally:
            asyncio.set_event_loop(None)
    else:
        module.run(testfunc)


async def test_start_soon_while_running() -> None:
    async def task_func() -> None:
        tg.start_soon(sleep, 0)

    async with create_task_group() as tg:
        tg.start_soon(task_func)


async def test_start_soon_after_error() -> None:
    with pytest.raises(ZeroDivisionError):
        async with create_task_group() as tg:
            a = 1 / 0  # noqa: F841

    with pytest.raises(RuntimeError) as exc:
        tg.start_soon(sleep, 0)

    exc.match('This task group is not active; no new tasks can be started')


async def test_start_no_value() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> None:
        task_status.started()

    async with create_task_group() as tg:
        value = await tg.start(taskfunc)
        assert value is None


async def test_start_called_twice() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> None:
        task_status.started()

        with pytest.raises(RuntimeError,
                           match="called 'started' twice on the same task status"):
            task_status.started()

    async with create_task_group() as tg:
        value = await tg.start(taskfunc)
        assert value is None


async def test_start_with_value() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> None:
        task_status.started('foo')

    async with create_task_group() as tg:
        value = await tg.start(taskfunc)
        assert value == 'foo'


async def test_start_crash_before_started_call() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> NoReturn:
        raise Exception('foo')

    async with create_task_group() as tg:
        with pytest.raises(Exception) as exc:
            await tg.start(taskfunc)

    exc.match('foo')


async def test_start_crash_after_started_call() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> NoReturn:
        task_status.started(2)
        raise Exception('foo')

    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            value = await tg.start(taskfunc)

    exc.match('foo')
    assert value == 2


async def test_start_no_started_call() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> None:
        pass

    async with create_task_group() as tg:
        with pytest.raises(RuntimeError) as exc:
            await tg.start(taskfunc)

    exc.match('hild exited')


async def test_start_cancelled() -> None:
    started = finished = False

    async def taskfunc(*, task_status: TaskStatus) -> None:
        nonlocal started, finished
        started = True
        await sleep(2)
        finished = True

    async with create_task_group() as tg:
        tg.cancel_scope.cancel()
        await tg.start(taskfunc)

    assert started
    assert not finished


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_start_native_host_cancelled() -> None:
    started = finished = False

    async def taskfunc(*, task_status: TaskStatus) -> None:
        nonlocal started, finished
        started = True
        await sleep(2)
        finished = True

    async def start_another() -> None:
        async with create_task_group() as tg:
            await tg.start(taskfunc)

    task = asyncio.get_event_loop().create_task(start_another())
    await wait_all_tasks_blocked()
    task.cancel()
    with pytest.raises(asyncio.CancelledError):
        await task

    assert started
    assert not finished


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_start_native_child_cancelled() -> None:
    task = None
    finished = False

    async def taskfunc(*, task_status: TaskStatus) -> None:
        nonlocal task, finished
        task = current_task()
        await sleep(2)
        finished = True

    async def start_another() -> None:
        async with create_task_group() as tg2:
            await tg2.start(taskfunc)

    async with create_task_group() as tg:
        tg.start_soon(start_another)
        await wait_all_tasks_blocked()
        assert task is not None
        task.cancel()

    assert not finished


async def test_start_exception_delivery() -> None:
    def task_fn(*, task_status: TaskStatus) -> None:
        task_status.started("hello")

    async with anyio.create_task_group() as tg:
        with pytest.raises(TypeError, match='to be synchronous$'):
            await tg.start(task_fn)  # type: ignore[arg-type]


async def test_host_exception() -> None:
    result = None

    async def set_result(value: str) -> None:
        nonlocal result
        await sleep(3)
        result = value

    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            tg.start_soon(set_result, 'a')
            raise Exception('dummy error')

    exc.match('dummy error')
    assert result is None


async def test_edge_cancellation() -> None:
    marker = None

    async def dummy() -> None:
        nonlocal marker
        marker = 1
        # At this point the task has been cancelled so sleep() will raise an exception
        await sleep(0)
        # Execution should never get this far
        marker = 2

    async with create_task_group() as tg:
        tg.start_soon(dummy)
        assert marker is None
        tg.cancel_scope.cancel()

    assert marker == 1


async def test_failing_child_task_cancels_host() -> None:
    async def child() -> NoReturn:
        await wait_all_tasks_blocked()
        raise Exception('foo')

    sleep_completed = False
    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            tg.start_soon(child)
            await sleep(0.5)
            sleep_completed = True

    exc.match('foo')
    assert not sleep_completed


async def test_failing_host_task_cancels_children() -> None:
    sleep_completed = False

    async def child() -> None:
        nonlocal sleep_completed
        await sleep(1)
        sleep_completed = True

    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            tg.start_soon(child)
            await wait_all_tasks_blocked()
            raise Exception('foo')

    exc.match('foo')
    assert not sleep_completed


async def test_cancel_scope_in_another_task() -> None:
    local_scope = None
    result = False

    async def child() -> None:
        nonlocal result, local_scope
        with CancelScope() as local_scope:
            await sleep(2)
            result = True

    async with create_task_group() as tg:
        tg.start_soon(child)
        while local_scope is None:
            await sleep(0)

        local_scope.cancel()

    assert not result


async def test_cancel_propagation() -> None:
    async def g() -> NoReturn:
        async with create_task_group():
            await sleep(1)

        assert False

    async with create_task_group() as tg:
        tg.start_soon(g)
        await sleep(0)
        tg.cancel_scope.cancel()


async def test_cancel_twice() -> None:
    """Test that the same task can receive two cancellations."""
    async def cancel_group() -> None:
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    for _ in range(2):
        async with create_task_group() as tg:
            tg.start_soon(cancel_group)
            await sleep(1)
            pytest.fail('Execution should not reach this point')


async def test_cancel_exiting_task_group() -> None:
    """
    Test that if a task group is waiting for subtasks to finish and it receives a cancellation, the
    subtasks are also cancelled and the waiting continues.

    """
    cancel_received = False

    async def waiter() -> None:
        nonlocal cancel_received
        try:
            await sleep(5)
        finally:
            cancel_received = True

    async def subgroup() -> None:
        async with create_task_group() as tg2:
            tg2.start_soon(waiter)

    async with create_task_group() as tg:
        tg.start_soon(subgroup)
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    assert cancel_received


async def test_exception_group_children() -> None:
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            tg.start_soon(async_error, 'task1')
            tg.start_soon(async_error, 'task2', 0.15)

    assert len(exc.value.exceptions) == 2
    assert sorted(str(e) for e in exc.value.exceptions) == ['task1', 'task2']
    assert exc.match('^2 exceptions were raised in the task group:\n')
    assert exc.match(r'Exception: task\d\n----')
    assert re.fullmatch(
        r"<ExceptionGroup: Exception\('task[12]',?\), Exception\('task[12]',?\)>",
        repr(exc.value))


async def test_exception_group_host() -> None:
    with pytest.raises(ExceptionGroup) as exc:
        async with create_task_group() as tg:
            tg.start_soon(async_error, 'child', 2)
            await wait_all_tasks_blocked()
            raise Exception('host')

    assert len(exc.value.exceptions) == 2
    assert sorted(str(e) for e in exc.value.exceptions) == ['child', 'host']
    assert exc.match('^2 exceptions were raised in the task group:\n')
    assert exc.match(r'Exception: host\n----')


async def test_escaping_cancelled_exception() -> None:
    async with create_task_group() as tg:
        tg.cancel_scope.cancel()
        await sleep(0)


async def test_cancel_scope_cleared() -> None:
    with move_on_after(0.1):
        await sleep(1)

    await sleep(0)


@pytest.mark.parametrize('delay', [0, 0.1], ids=['instant', 'delayed'])
async def test_fail_after(delay: float) -> None:
    with pytest.raises(TimeoutError):
        with fail_after(delay) as scope:
            await sleep(1)

    assert scope.cancel_called


async def test_fail_after_no_timeout() -> None:
    with fail_after(None) as scope:
        assert scope.deadline == float('inf')
        await sleep(0.1)

    assert not scope.cancel_called


async def test_fail_after_after_cancellation() -> None:
    event = anyio.Event()
    async with anyio.create_task_group() as tg:
        tg.cancel_scope.cancel()
        await event.wait()

    block_complete = False
    with pytest.raises(TimeoutError):
        with fail_after(0.1):
            await anyio.sleep(0.5)
            block_complete = True

    assert not block_complete


@pytest.mark.parametrize('delay', [0, 0.1], ids=['instant', 'delayed'])
async def test_move_on_after(delay: float) -> None:
    result = False
    with move_on_after(delay) as scope:
        await sleep(1)
        result = True

    assert not result
    assert scope.cancel_called


async def test_move_on_after_no_timeout() -> None:
    result = False
    with move_on_after(None) as scope:
        assert scope.deadline == float('inf')
        await sleep(0.1)
        result = True

    assert result
    assert not scope.cancel_called


async def test_nested_move_on_after() -> None:
    sleep_completed = inner_scope_completed = False
    with move_on_after(0.1) as outer_scope:
        assert current_effective_deadline() == outer_scope.deadline
        with move_on_after(1) as inner_scope:
            assert current_effective_deadline() == outer_scope.deadline
            await sleep(2)
            sleep_completed = True

        inner_scope_completed = True

    assert not sleep_completed
    assert not inner_scope_completed
    assert outer_scope.cancel_called
    assert not inner_scope.cancel_called


async def test_shielding() -> None:
    async def cancel_when_ready() -> None:
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    inner_sleep_completed = outer_sleep_completed = False
    async with create_task_group() as tg:
        tg.start_soon(cancel_when_ready)
        with move_on_after(10, shield=True) as inner_scope:
            assert inner_scope.shield
            await sleep(0.1)
            inner_sleep_completed = True

        await sleep(1)
        outer_sleep_completed = True

    assert inner_sleep_completed
    assert not outer_sleep_completed
    assert tg.cancel_scope.cancel_called
    assert not inner_scope.cancel_called


async def test_cancel_from_shielded_scope() -> None:
    async with create_task_group() as tg:
        with CancelScope(shield=True) as inner_scope:
            assert inner_scope.shield
            tg.cancel_scope.cancel()

        with pytest.raises(get_cancelled_exc_class()):
            await sleep(0.01)

        with pytest.raises(get_cancelled_exc_class()):
            await sleep(0.01)


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cancel_host_asyncgen() -> None:
    done = False

    async def host_task() -> None:
        nonlocal done
        async with create_task_group() as tg:
            with CancelScope(shield=True) as inner_scope:
                assert inner_scope.shield
                tg.cancel_scope.cancel()

            with pytest.raises(get_cancelled_exc_class()):
                await sleep(0)

            with pytest.raises(get_cancelled_exc_class()):
                await sleep(0)

            done = True

    async def host_agen_fn() -> AsyncGenerator[None, None]:
        await host_task()
        yield
        pytest.fail("host_agen_fn should only be __anext__ed once")

    host_agen = host_agen_fn()
    try:
        await asyncio.get_event_loop().create_task(host_agen.__anext__())
    finally:
        await host_agen.aclose()

    assert done


async def test_shielding_immediate_scope_cancelled() -> None:
    async def cancel_when_ready() -> None:
        await wait_all_tasks_blocked()
        scope.cancel()

    sleep_completed = False
    async with create_task_group() as tg:
        with CancelScope(shield=True) as scope:
            tg.start_soon(cancel_when_ready)
            await sleep(0.5)
            sleep_completed = True

    assert not sleep_completed


async def test_shielding_mutate() -> None:
    completed = False

    async def task(task_status: TaskStatus) -> NoReturn:  # type: ignore[misc]
        nonlocal completed
        with CancelScope() as scope:
            # Enable the shield a little after the scope starts to make this test
            # general, even though it has no bearing on the current implementation.
            await sleep(.1)
            scope.shield = True
            task_status.started()
            await sleep(.1)
            completed = True
            scope.shield = False
            await sleep(1)
            pytest.fail('Execution should not reach this point')

    async with create_task_group() as tg:
        await tg.start(task)
        tg.cancel_scope.cancel()

    assert completed


async def test_cancel_scope_in_child_task() -> None:
    child_scope = None

    async def child() -> None:
        nonlocal child_scope
        with CancelScope() as child_scope:
            await sleep(2)

    host_done = False
    async with create_task_group() as tg:
        tg.start_soon(child)
        await wait_all_tasks_blocked()
        assert child_scope is not None
        child_scope.cancel()
        await sleep(0.1)
        host_done = True

    assert host_done
    assert not tg.cancel_scope.cancel_called


async def test_exception_cancels_siblings() -> None:
    sleep_completed = False

    async def child(fail: bool) -> None:
        if fail:
            raise Exception('foo')
        else:
            nonlocal sleep_completed
            await sleep(1)
            sleep_completed = True

    with pytest.raises(Exception) as exc:
        async with create_task_group() as tg:
            tg.start_soon(child, False)
            await wait_all_tasks_blocked()
            tg.start_soon(child, True)

    exc.match('foo')
    assert not sleep_completed


async def test_cancel_cascade() -> None:
    async def do_something() -> NoReturn:
        async with create_task_group() as tg2:
            tg2.start_soon(sleep, 1)

        raise Exception('foo')

    async with create_task_group() as tg:
        tg.start_soon(do_something)
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()


async def test_cancelled_parent() -> None:
    async def child() -> NoReturn:
        with CancelScope():
            await sleep(1)

        raise Exception('foo')

    async def parent(tg: TaskGroup) -> None:
        await wait_all_tasks_blocked()
        tg.start_soon(child)

    async with create_task_group() as tg:
        tg.start_soon(parent, tg)
        tg.cancel_scope.cancel()


async def test_shielded_deadline() -> None:
    with move_on_after(10):
        with CancelScope(shield=True):
            with move_on_after(1000):
                assert current_effective_deadline() - current_time() > 900


async def test_deadline_reached_on_start() -> None:
    with move_on_after(0):
        await sleep(0)
        pytest.fail('Execution should not reach this point')


async def test_deadline_moved() -> None:
    with fail_after(0.1) as scope:
        scope.deadline += 0.3
        await sleep(0.2)


async def test_timeout_error_with_multiple_cancellations() -> None:
    with pytest.raises(TimeoutError):
        with fail_after(0.1):
            async with create_task_group() as tg:
                tg.start_soon(sleep, 2)
                await sleep(2)


async def test_nested_fail_after() -> None:
    async def killer(scope: CancelScope) -> None:
        await wait_all_tasks_blocked()
        scope.cancel()

    async with create_task_group() as tg:
        with CancelScope() as scope:
            with CancelScope():
                tg.start_soon(killer, scope)
                with fail_after(1):
                    await sleep(2)
                    pytest.fail('Execution should not reach this point')

                pytest.fail('Execution should not reach this point either')

            pytest.fail('Execution should also not reach this point')

    assert scope.cancel_called


async def test_nested_shield() -> None:
    async def killer(scope: CancelScope) -> None:
        await wait_all_tasks_blocked()
        scope.cancel()

    with pytest.raises(TimeoutError):
        async with create_task_group() as tg:
            with CancelScope() as scope:
                with CancelScope(shield=True):
                    tg.start_soon(killer, scope)
                    with fail_after(0.2):
                        await sleep(2)


def test_task_group_in_generator(anyio_backend_name: str,
                                 anyio_backend_options: Dict[str, Any]) -> None:
    async def task_group_generator() -> AsyncGenerator[None, None]:
        async with create_task_group():
            yield

    gen = task_group_generator()
    anyio.run(gen.__anext__, backend=anyio_backend_name,  # type: ignore[arg-type]
              backend_options=anyio_backend_options)
    pytest.raises(StopAsyncIteration, anyio.run, gen.__anext__, backend=anyio_backend_name,
                  backend_options=anyio_backend_options)


async def test_exception_group_filtering() -> None:
    """Test that CancelledErrors are filtered out of nested exception groups."""

    async def fail(name: str) -> NoReturn:
        try:
            await anyio.sleep(.1)
        finally:
            raise Exception('%s task failed' % name)

    async def fn() -> None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(fail, 'parent')
            async with anyio.create_task_group() as tg2:
                tg2.start_soon(fail, 'child')
                await anyio.sleep(1)

    with pytest.raises(ExceptionGroup) as exc:
        await fn()

    assert len(exc.value.exceptions) == 2
    assert str(exc.value.exceptions[0]) == 'parent task failed'
    assert str(exc.value.exceptions[1]) == 'child task failed'


async def test_cancel_propagation_with_inner_spawn() -> None:
    async def g() -> NoReturn:
        async with anyio.create_task_group() as tg2:
            tg2.start_soon(anyio.sleep, 10)
            await anyio.sleep(1)

        assert False

    async with anyio.create_task_group() as tg:
        tg.start_soon(g)
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()


async def test_escaping_cancelled_error_from_cancelled_task() -> None:
    """Regression test for issue #88. No CancelledError should escape the outer scope."""
    with CancelScope() as scope:
        with move_on_after(0.1):
            await sleep(1)

        scope.cancel()


@pytest.mark.filterwarnings('ignore:"@coroutine" decorator is deprecated:DeprecationWarning')
def test_cancel_generator_based_task() -> None:
    from asyncio import coroutine

    async def native_coro_part() -> None:
        with CancelScope() as scope:
            scope.cancel()

    @coroutine
    def generator_part() -> Generator[object, BaseException, None]:
        yield from native_coro_part()

    anyio.run(generator_part, backend='asyncio')  # type: ignore[arg-type]


async def test_suppress_exception_context() -> None:
    """
    Test that the __context__ attribute has been cleared when the exception is re-raised in the
    exception group. This prevents recursive tracebacks.

    """
    with pytest.raises(ValueError) as exc:
        async with create_task_group() as tg:
            tg.cancel_scope.cancel()
            async with create_task_group() as tg2:
                tg2.start_soon(sleep, 1)
                raise ValueError

    assert exc.value.__context__ is None


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cancel_native_future_tasks() -> None:
    async def wait_native_future() -> None:
        loop = asyncio.get_event_loop()
        await loop.create_future()

    async with anyio.create_task_group() as tg:
        tg.start_soon(wait_native_future)
        tg.cancel_scope.cancel()


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cancel_native_future_tasks_cancel_scope() -> None:
    async def wait_native_future() -> None:
        with anyio.CancelScope():
            loop = asyncio.get_event_loop()
            await loop.create_future()

    async with anyio.create_task_group() as tg:
        tg.start_soon(wait_native_future)
        tg.cancel_scope.cancel()


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cancel_completed_task() -> None:
    loop = asyncio.get_event_loop()
    old_exception_handler = loop.get_exception_handler()
    exceptions = []

    def exception_handler(*args: object, **kwargs: object) -> None:
        exceptions.append((args, kwargs))

    loop.set_exception_handler(exception_handler)
    try:
        async def noop() -> None:
            pass

        async with anyio.create_task_group() as tg:
            tg.start_soon(noop)
            tg.cancel_scope.cancel()

        assert exceptions == []
    finally:
        loop.set_exception_handler(old_exception_handler)


async def test_task_in_sync_spawn_callback() -> None:
    outer_task_id = anyio.get_current_task().id
    inner_task_id = None

    def task_wrap() -> Coroutine[object, object, None]:
        assert anyio.get_current_task().id == outer_task_id

        async def corofn() -> None:
            nonlocal inner_task_id
            inner_task_id = anyio.get_current_task().id

        return corofn()

    async with create_task_group() as tg:
        tg.start_soon(task_wrap)

    assert inner_task_id is not None
    assert inner_task_id != outer_task_id


async def test_shielded_cancel_sleep_time() -> None:
    """Test that cancelling a shielded tasks spends more time sleeping than cancelling."""
    event = anyio.Event()
    hang_time = 0.2

    async def set_event() -> None:
        await sleep(hang_time)
        event.set()

    async def never_cancel_task() -> None:
        with CancelScope(shield=True):
            await sleep(0.2)
            await event.wait()

    async with create_task_group() as tg:
        tg.start_soon(set_event)

        async with create_task_group() as tg:
            tg.start_soon(never_cancel_task)
            tg.cancel_scope.cancel()
            process_time = time.process_time()

        assert (time.process_time() - process_time) < hang_time


async def test_cancelscope_wrong_exit_order() -> None:
    """
    Test that a RuntimeError is raised if the task tries to exit cancel scopes in the wrong order.

    """
    scope1 = CancelScope()
    scope2 = CancelScope()
    scope1.__enter__()
    scope2.__enter__()
    pytest.raises(RuntimeError, scope1.__exit__, None, None, None)


async def test_cancelscope_exit_before_enter() -> None:
    """Test that a RuntimeError is raised if one tries to exit a cancel scope before entering."""
    scope = CancelScope()
    pytest.raises(RuntimeError, scope.__exit__, None, None, None)


@pytest.mark.parametrize('anyio_backend', ['asyncio'])  # trio does not check for this yet
async def test_cancelscope_exit_in_wrong_task() -> None:
    async def enter_scope(scope: CancelScope) -> None:
        scope.__enter__()

    async def exit_scope(scope: CancelScope) -> None:
        scope.__exit__(None, None, None)

    scope = CancelScope()
    async with create_task_group() as tg:
        tg.start_soon(enter_scope, scope)

    with pytest.raises(RuntimeError):
        async with create_task_group() as tg:
            tg.start_soon(exit_scope, scope)


def test_unhandled_exception_group(caplog: pytest.LogCaptureFixture) -> None:
    def crash() -> NoReturn:
        raise KeyboardInterrupt

    async def nested() -> None:
        async with anyio.create_task_group() as tg:
            tg.start_soon(anyio.sleep, 5)
            await anyio.sleep(5)

    async def main() -> NoReturn:  # type: ignore[misc]
        async with anyio.create_task_group() as tg:
            tg.start_soon(nested)
            await wait_all_tasks_blocked()
            asyncio.get_event_loop().call_soon(crash)
            await anyio.sleep(5)

        pytest.fail('Execution should never reach this point')

    with pytest.raises(KeyboardInterrupt):
        anyio.run(main, backend='asyncio')

    assert not caplog.messages


@pytest.mark.skipif(sys.version_info < (3, 9),
                    reason='Cancel messages are only supported on py3.9+')
@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_cancellederror_combination_with_message() -> None:
    async def taskfunc(*, task_status: TaskStatus) -> NoReturn:  # type: ignore[misc]
        task_status.started(asyncio.current_task())
        await sleep(5)
        pytest.fail('Execution should never reach this point')

    with pytest.raises(asyncio.CancelledError, match='blah'):
        async with create_task_group() as tg:
            task = await tg.start(taskfunc)
            tg.start_soon(sleep, 5)
            await wait_all_tasks_blocked()
            assert isinstance(task, asyncio.Task)
            task.cancel('blah')
