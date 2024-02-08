from __future__ import annotations

import math
import sys
import threading
import time
from collections.abc import Awaitable, Callable
from concurrent import futures
from concurrent.futures import CancelledError, Future
from contextlib import asynccontextmanager, suppress
from contextvars import ContextVar
from typing import Any, AsyncGenerator, Literal, NoReturn, TypeVar

import pytest
import sniffio
from _pytest.logging import LogCaptureFixture

from anyio import (
    CancelScope,
    Event,
    create_task_group,
    fail_after,
    from_thread,
    get_all_backends,
    get_cancelled_exc_class,
    get_current_task,
    run,
    sleep,
    to_thread,
    wait_all_tasks_blocked,
)
from anyio.abc import TaskStatus
from anyio.from_thread import BlockingPortal, start_blocking_portal
from anyio.lowlevel import checkpoint

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup, ExceptionGroup

pytestmark = pytest.mark.anyio

T_Retval = TypeVar("T_Retval")


async def async_add(a: int, b: int) -> int:
    assert threading.current_thread() is threading.main_thread()
    return a + b


async def asyncgen_add(a: int, b: int) -> AsyncGenerator[int, Any]:
    yield a + b


def sync_add(a: int, b: int) -> int:
    assert threading.current_thread() is threading.main_thread()
    return a + b


def thread_worker_async(
    func: Callable[..., Awaitable[T_Retval]], *args: Any
) -> T_Retval:
    assert threading.current_thread() is not threading.main_thread()
    return from_thread.run(func, *args)


def thread_worker_sync(func: Callable[..., T_Retval], *args: Any) -> T_Retval:
    assert threading.current_thread() is not threading.main_thread()
    return from_thread.run_sync(func, *args)


@pytest.mark.parametrize("cancel", [True, False])
async def test_thread_cancelled(cancel: bool) -> None:
    event = threading.Event()
    thread_finished_future: Future[None] = Future()

    def sync_function() -> None:
        event.wait(3)
        try:
            from_thread.check_cancelled()
        except BaseException as exc:
            thread_finished_future.set_exception(exc)
        else:
            thread_finished_future.set_result(None)

    async with create_task_group() as tg:
        tg.start_soon(to_thread.run_sync, sync_function)
        await wait_all_tasks_blocked()
        if cancel:
            tg.cancel_scope.cancel()

        event.set()

    if cancel:
        with pytest.raises(get_cancelled_exc_class()):
            thread_finished_future.result(3)
    else:
        thread_finished_future.result(3)


async def test_thread_cancelled_and_abandoned() -> None:
    event = threading.Event()
    thread_finished_future: Future[None] = Future()

    def sync_function() -> None:
        event.wait(3)
        try:
            from_thread.check_cancelled()
        except BaseException as exc:
            thread_finished_future.set_exception(exc)
        else:
            thread_finished_future.set_result(None)

    async with create_task_group() as tg:
        tg.start_soon(lambda: to_thread.run_sync(sync_function, abandon_on_cancel=True))
        await wait_all_tasks_blocked()
        tg.cancel_scope.cancel()

    event.set()
    with pytest.raises(get_cancelled_exc_class()):
        thread_finished_future.result(3)


async def test_cancelscope_propagation() -> None:
    async def async_time_bomb() -> None:
        cancel_scope.cancel()
        with fail_after(1):
            await sleep(3)

    with CancelScope() as cancel_scope:
        await to_thread.run_sync(from_thread.run, async_time_bomb)

    assert cancel_scope.cancelled_caught


async def test_cancelscope_propagation_when_abandoned() -> None:
    host_cancelled_event = Event()
    completed_event = Event()

    async def async_time_bomb() -> None:
        cancel_scope.cancel()
        with fail_after(3):
            await host_cancelled_event.wait()

        completed_event.set()

    with CancelScope() as cancel_scope:
        await to_thread.run_sync(
            from_thread.run, async_time_bomb, abandon_on_cancel=True
        )

    assert cancel_scope.cancelled_caught
    host_cancelled_event.set()
    with fail_after(3):
        await completed_event.wait()


class TestRunAsyncFromThread:
    async def test_run_corofunc_from_thread(self) -> None:
        result = await to_thread.run_sync(thread_worker_async, async_add, 1, 2)
        assert result == 3

    async def test_run_asyncgen_from_thread(self) -> None:
        gen = asyncgen_add(1, 2)
        try:
            result = await to_thread.run_sync(thread_worker_async, gen.__anext__)
            assert result == 3
        finally:
            await gen.aclose()

    async def test_run_sync_from_thread(self) -> None:
        result = await to_thread.run_sync(thread_worker_sync, sync_add, 1, 2)
        assert result == 3

    def test_run_sync_from_thread_pooling(self) -> None:
        async def main() -> None:
            thread_ids = set()
            for _ in range(5):
                thread_ids.add(await to_thread.run_sync(threading.get_ident))

            # Expects that all the work has been done in the same worker thread
            assert len(thread_ids) == 1
            assert thread_ids.pop() != threading.get_ident()
            assert threading.active_count() == initial_count + 1

        # The thread should not exist after the event loop has been closed
        initial_count = threading.active_count()
        run(main, backend="asyncio")

        for _ in range(10):
            if threading.active_count() == initial_count:
                return

            time.sleep(0.1)

        pytest.fail("Worker thread did not exit within 1 second")

    async def test_run_async_from_thread_exception(self) -> None:
        with pytest.raises(TypeError) as exc:
            await to_thread.run_sync(thread_worker_async, async_add, 1, "foo")

        exc.match("unsupported operand type")

    async def test_run_sync_from_thread_exception(self) -> None:
        with pytest.raises(TypeError) as exc:
            await to_thread.run_sync(thread_worker_sync, sync_add, 1, "foo")

        exc.match("unsupported operand type")

    async def test_run_anyio_async_func_from_thread(self) -> None:
        def worker(delay: float) -> Literal[True]:
            from_thread.run(sleep, delay)
            return True

        assert await to_thread.run_sync(worker, 0)

    def test_run_async_from_unclaimed_thread(self) -> None:
        async def foo() -> None:
            pass

        exc = pytest.raises(RuntimeError, from_thread.run, foo)
        exc.match("This function can only be run from an AnyIO worker thread")

    async def test_contextvar_propagation(self, anyio_backend_name: str) -> None:
        var = ContextVar("var", default=1)

        async def async_func() -> int:
            await checkpoint()
            return var.get()

        def worker() -> int:
            var.set(6)
            return from_thread.run(async_func)

        assert await to_thread.run_sync(worker) == 6

    async def test_sniffio(self, anyio_backend_name: str) -> None:
        async def async_func() -> str:
            return sniffio.current_async_library()

        def worker() -> str:
            sniffio.current_async_library_cvar.set("something invalid for async_func")
            return from_thread.run(async_func)

        assert await to_thread.run_sync(worker) == anyio_backend_name


class TestRunSyncFromThread:
    def test_run_sync_from_unclaimed_thread(self) -> None:
        def foo() -> None:
            pass

        exc = pytest.raises(RuntimeError, from_thread.run_sync, foo)
        exc.match("This function can only be run from an AnyIO worker thread")

    async def test_contextvar_propagation(self) -> None:
        var = ContextVar("var", default=1)

        def worker() -> int:
            var.set(6)
            return from_thread.run_sync(var.get)

        assert await to_thread.run_sync(worker) == 6

    async def test_sniffio(self, anyio_backend_name: str) -> None:
        def worker() -> str:
            sniffio.current_async_library_cvar.set("something invalid for async_func")
            return from_thread.run_sync(sniffio.current_async_library)

        assert await to_thread.run_sync(worker) == anyio_backend_name


class TestBlockingPortal:
    class AsyncCM:
        def __init__(self, ignore_error: bool):
            self.ignore_error = ignore_error

        async def __aenter__(self) -> Literal["test"]:
            return "test"

        async def __aexit__(
            self, exc_type: object, exc_val: object, exc_tb: object
        ) -> bool:
            return self.ignore_error

    async def test_call_corofunc(self) -> None:
        async with BlockingPortal() as portal:
            result = await to_thread.run_sync(portal.call, async_add, 1, 2)
            assert result == 3

    async def test_call_anext(self) -> None:
        gen = asyncgen_add(1, 2)
        try:
            async with BlockingPortal() as portal:
                result = await to_thread.run_sync(portal.call, gen.__anext__)
                assert result == 3
        finally:
            await gen.aclose()

    async def test_aexit_with_exception(self) -> None:
        """
        Test that when the portal exits with an exception, all tasks are cancelled.

        """

        def external_thread() -> None:
            try:
                portal.call(sleep, 3)
            except BaseException as exc:
                results.append(exc)
            else:
                results.append(None)

        results: list[BaseException | None] = []
        with suppress(Exception):
            async with BlockingPortal() as portal:
                thread1 = threading.Thread(target=external_thread)
                thread1.start()
                thread2 = threading.Thread(target=external_thread)
                thread2.start()
                await sleep(0.1)
                assert not results
                raise Exception

        await to_thread.run_sync(thread1.join)
        await to_thread.run_sync(thread2.join)

        assert len(results) == 2
        assert isinstance(results[0], CancelledError)
        assert isinstance(results[1], CancelledError)

    async def test_aexit_without_exception(self) -> None:
        """Test that when the portal exits, it waits for all tasks to finish."""

        def external_thread() -> None:
            try:
                portal.call(sleep, 0.2)
            except BaseException as exc:
                results.append(exc)
            else:
                results.append(None)

        results: list[BaseException | None] = []
        async with BlockingPortal() as portal:
            thread1 = threading.Thread(target=external_thread)
            thread1.start()
            thread2 = threading.Thread(target=external_thread)
            thread2.start()
            await sleep(0.1)
            assert not results

        await to_thread.run_sync(thread1.join)
        await to_thread.run_sync(thread2.join)

        assert results == [None, None]

    async def test_call_portal_from_event_loop_thread(self) -> None:
        async with BlockingPortal() as portal:
            exc = pytest.raises(RuntimeError, portal.call, threading.get_ident)
            exc.match("This method cannot be called from the event loop thread")

    def test_start_with_new_event_loop(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def async_get_thread_id() -> int:
            return threading.get_ident()

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            thread_id = portal.call(async_get_thread_id)

        assert isinstance(thread_id, int)
        assert thread_id != threading.get_ident()

    def test_start_with_nonexistent_backend(self) -> None:
        with pytest.raises(LookupError) as exc:
            with start_blocking_portal("foo"):
                pass

        exc.match("No such backend: foo")

    def test_call_stopped_portal(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            pass

        pytest.raises(RuntimeError, portal.call, threading.get_ident).match(
            "This portal is not running"
        )

    def test_start_task_soon(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def event_waiter() -> Literal["test"]:
            await event1.wait()
            event2.set()
            return "test"

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            event1 = portal.call(Event)
            event2 = portal.call(Event)
            future = portal.start_task_soon(event_waiter)
            portal.call(event1.set)
            portal.call(event2.wait)
            assert future.result() == "test"

    def test_start_task_soon_cancel_later(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def noop() -> None:
            await sleep(2)

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future = portal.start_task_soon(noop)
            portal.call(wait_all_tasks_blocked)
            future.cancel()

        assert future.cancelled()

    def test_start_task_soon_cancel_immediately(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        cancelled = False

        async def event_waiter() -> None:
            nonlocal cancelled
            try:
                await sleep(3)
            except get_cancelled_exc_class():
                cancelled = True

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future = portal.start_task_soon(event_waiter)
            future.cancel()

        assert cancelled

    def test_start_task_soon_with_name(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        task_name = None

        async def taskfunc() -> None:
            nonlocal task_name
            task_name = get_current_task().name

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            portal.start_task_soon(taskfunc, name="testname")

        assert task_name == "testname"

    def test_async_context_manager_success(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with portal.wrap_async_context_manager(
                TestBlockingPortal.AsyncCM(False)
            ) as cm:
                assert cm == "test"

    def test_async_context_manager_error(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(Exception) as exc:
                with portal.wrap_async_context_manager(
                    TestBlockingPortal.AsyncCM(False)
                ) as cm:
                    assert cm == "test"
                    raise Exception("should NOT be ignored")

                exc.match("should NOT be ignored")

    def test_async_context_manager_error_ignore(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with portal.wrap_async_context_manager(
                TestBlockingPortal.AsyncCM(True)
            ) as cm:
                assert cm == "test"
                raise Exception("should be ignored")

    def test_async_context_manager_exception_in_task_group(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        """Regression test for #381."""

        async def failing_func() -> None:
            0 / 0

        @asynccontextmanager
        async def run_in_context() -> AsyncGenerator[None, None]:
            async with create_task_group() as tg:
                tg.start_soon(failing_func)
                yield

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(ExceptionGroup) as exc:
                with portal.wrap_async_context_manager(run_in_context()):
                    pass

            assert len(exc.value.exceptions) == 1
            assert isinstance(exc.value.exceptions[0], ZeroDivisionError)

    def test_start_no_value(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def taskfunc(*, task_status: TaskStatus) -> None:
            task_status.started()

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, value = portal.start_task(taskfunc)
            assert value is None
            assert future.result() is None

    def test_start_with_value(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def taskfunc(*, task_status: TaskStatus) -> None:
            task_status.started("foo")

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, value = portal.start_task(taskfunc)
            assert value == "foo"
            assert future.result() is None

    def test_start_crash_before_started_call(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def taskfunc(*, task_status: object) -> NoReturn:
            raise Exception("foo")

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(Exception, match="foo"):
                portal.start_task(taskfunc)

    def test_start_crash_after_started_call(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def taskfunc(*, task_status: TaskStatus) -> NoReturn:
            task_status.started(2)
            raise Exception("foo")

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, value = portal.start_task(taskfunc)
            assert value == 2
            with pytest.raises(Exception, match="foo"):
                future.result()

    def test_start_no_started_call(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def taskfunc(*, task_status: TaskStatus) -> None:
            pass

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            with pytest.raises(RuntimeError, match="Task exited"):
                portal.start_task(taskfunc)

    def test_start_with_name(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        async def taskfunc(*, task_status: TaskStatus) -> None:
            task_status.started(get_current_task().name)

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            future, start_value = portal.start_task(taskfunc, name="testname")
            assert start_value == "testname"

    def test_contextvar_propagation_sync(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        var = ContextVar("var", default=1)
        var.set(6)
        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            propagated_value = portal.call(var.get)

        assert propagated_value == 6

    def test_contextvar_propagation_async(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        var = ContextVar("var", default=1)
        var.set(6)

        async def get_var() -> int:
            await checkpoint()
            return var.get()

        with start_blocking_portal(anyio_backend_name, anyio_backend_options) as portal:
            propagated_value = portal.call(get_var)

        assert propagated_value == 6

    @pytest.mark.parametrize("anyio_backend", ["asyncio"])
    async def test_asyncio_run_sync_called(self, caplog: LogCaptureFixture) -> None:
        """Regression test for #357."""

        async def in_loop() -> None:
            raise CancelledError

        async with BlockingPortal() as portal:
            await to_thread.run_sync(portal.start_task_soon, in_loop)

        assert not caplog.text

    def test_raise_baseexception_from_task(
        self, anyio_backend_name: str, anyio_backend_options: dict[str, Any]
    ) -> None:
        """
        Test that when a task raises a BaseException, it does not trigger additional
        exceptions when trying to close the portal.

        """

        async def raise_baseexception() -> None:
            raise BaseException("fatal error")

        with pytest.raises(BaseExceptionGroup) as outer_exc:
            with start_blocking_portal(
                anyio_backend_name, anyio_backend_options
            ) as portal:
                with pytest.raises(BaseException, match="fatal error") as exc:
                    portal.call(raise_baseexception)

                assert exc.value.__context__ is None

        assert len(outer_exc.value.exceptions) == 1
        assert str(outer_exc.value.exceptions[0]) == "fatal error"

    @pytest.mark.parametrize("portal_backend_name", get_all_backends())
    async def test_from_async(
        self, anyio_backend_name: str, portal_backend_name: str
    ) -> None:
        """
        Test that portals don't deadlock when started/used from async code.

        Note: This test will deadlock if there is a regression. A deadlock should be
        treated as a failure. See also
        https://github.com/agronholm/anyio/pull/524#discussion_r1183080886.

        """
        if anyio_backend_name == "trio" and portal_backend_name == "trio":
            pytest.xfail("known bug (#525)")

        with start_blocking_portal(portal_backend_name) as portal:
            portal.call(checkpoint)

    async def test_cancel_portal_future(self) -> None:
        """Regression test for #575."""
        event = Event()

        def sync_thread() -> None:
            fs = [portal.start_task_soon(sleep, math.inf)]
            from_thread.run_sync(event.set)
            done, not_done = futures.wait(
                fs, timeout=1, return_when=futures.FIRST_COMPLETED
            )
            assert not not_done

        async with from_thread.BlockingPortal() as portal:
            async with create_task_group() as tg:
                tg.start_soon(to_thread.run_sync, sync_thread)
                # Ensure thread has time to start the task
                await event.wait()
                await portal.stop(cancel_remaining=True)
