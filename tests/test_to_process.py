from __future__ import annotations

import os
import sys
import time
from functools import partial
from unittest.mock import Mock

import pytest

from anyio import (
    CancelScope,
    create_task_group,
    fail_after,
    to_process,
    wait_all_tasks_blocked,
)
from anyio.abc import Process

pytestmark = pytest.mark.anyio


async def test_run_sync_in_process_pool() -> None:
    """
    Test that the function runs in a different process, and the same process in both
    calls.

    """
    worker_pid = await to_process.run_sync(os.getpid)
    assert worker_pid != os.getpid()
    assert await to_process.run_sync(os.getpid) == worker_pid


async def test_identical_sys_path() -> None:
    """Test that partial() can be used to pass keyword arguments."""
    assert await to_process.run_sync(eval, "sys.path") == sys.path


async def test_partial() -> None:
    """Test that partial() can be used to pass keyword arguments."""
    assert await to_process.run_sync(partial(sorted, reverse=True), ["a", "b"]) == [
        "b",
        "a",
    ]


async def test_exception() -> None:
    """Test that exceptions are delivered properly."""
    with pytest.raises(ValueError, match="invalid literal for int"):
        assert await to_process.run_sync(int, "a")


async def test_print() -> None:
    """Test that print() won't interfere with parent-worker communication."""
    worker_pid = await to_process.run_sync(os.getpid)
    await to_process.run_sync(print, "hello")
    await to_process.run_sync(print, "world")
    assert await to_process.run_sync(os.getpid) == worker_pid


async def test_cancel_before() -> None:
    """
    Test that starting to_process.run_sync() in a cancelled scope does not cause a
    worker process to be reserved.

    """
    with CancelScope() as scope:
        scope.cancel()
        await to_process.run_sync(os.getpid)

    pytest.raises(LookupError, to_process._process_pool_workers.get)


async def test_cancel_during() -> None:
    """
    Test that cancelling an operation on the worker process causes the process to be
    killed.

    """
    worker_pid = await to_process.run_sync(os.getpid)
    with fail_after(4):
        async with create_task_group() as tg:
            tg.start_soon(partial(to_process.run_sync, cancellable=True), time.sleep, 5)
            await wait_all_tasks_blocked()
            tg.cancel_scope.cancel()

    # The previous worker was killed so we should get a new one now
    assert await to_process.run_sync(os.getpid) != worker_pid


async def test_exec_while_pruning() -> None:
    """
    Test that in the case when one or more idle workers are pruned, the originally
    selected idle worker is re-added to the queue of idle workers.
    """

    worker_pid1 = await to_process.run_sync(os.getpid)
    workers = to_process._process_pool_workers.get()
    idle_workers = to_process._process_pool_idle_workers.get()
    real_worker = next(iter(workers))

    fake_idle_process = Mock(Process)
    workers.add(fake_idle_process)
    try:
        # Add a mock worker process that's guaranteed to be eligible for pruning
        idle_workers.appendleft(
            (fake_idle_process, -to_process.WORKER_MAX_IDLE_TIME - 1)
        )

        worker_pid2 = await to_process.run_sync(os.getpid)
        assert worker_pid1 == worker_pid2
        fake_idle_process.kill.assert_called_once_with()
        assert idle_workers[0][0] is real_worker
    finally:
        workers.discard(fake_idle_process)
