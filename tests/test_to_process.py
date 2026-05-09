from __future__ import annotations

import os
import sys
import time
from functools import partial
from pathlib import Path
from unittest.mock import Mock

import pytest
from pytest import MonkeyPatch

from anyio import (
    CancelScope,
    create_task_group,
    fail_after,
    to_process,
    wait_all_tasks_blocked,
)
from anyio.abc import Process


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


@pytest.mark.usefixtures("deactivate_blockbuster")
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


async def test_nonexistent_main_module(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """
    Test that worker process creation won't fail if the detected path to the `__main__`
    module doesn't exist. Regression test for #696.
    """

    script_path = tmp_path / "badscript"
    script_path.touch()
    monkeypatch.setattr("__main__.__file__", str(script_path / "__main__.py"))
    await to_process.run_sync(os.getpid)


def _import_main() -> str:
    # Runs in the worker process. dill, pickle and several other libraries
    # assume "import __main__" works; make the assumption explicit so the
    # regression has a concrete failure mode (ModuleNotFoundError on master).
    import __main__

    return type(__main__).__name__


async def test_main_module_with_non_py_path(
    monkeypatch: MonkeyPatch, tmp_path: Path
) -> None:
    """
    Regression test for #1027.

    When AnyIO's worker process is launched from a console-script entry point
    (so ``__main__.__file__`` is a path *without* a ``.py`` / ``.pyc`` suffix),
    ``importlib.util.spec_from_file_location`` returns ``None`` and the worker
    used to drop ``__main__`` from ``sys.modules`` permanently. Subsequent
    ``import __main__`` calls in user code (dill et al.) then raised
    ``ModuleNotFoundError``.
    """

    # Create an existing file with no .py / .pyc suffix - mimics an installed
    # console-script entry point.
    script_path = tmp_path / "myapp"
    script_path.write_text("#!/usr/bin/env python\n")
    monkeypatch.setattr("__main__.__file__", str(script_path))

    # On master this raises BrokenWorkerProcess (ModuleNotFoundError: '__main__')
    # in the worker; with the fix, __main__ is restored and the import works.
    assert await to_process.run_sync(_import_main) == "module"
