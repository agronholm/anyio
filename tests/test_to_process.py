from __future__ import annotations

import os
import pickle
import sys
import time
from functools import partial
from pathlib import Path
from typing import NoReturn
from unittest.mock import Mock

import pytest
from pytest import MonkeyPatch
from pytest_mock import MockerFixture

from anyio import (
    BrokenWorkerProcess,
    CancelScope,
    create_task_group,
    fail_after,
    to_process,
    wait_all_tasks_blocked,
)
from anyio.abc import Process

if sys.version_info < (3, 11):
    from exceptiongroup import ExceptionGroup, format_exception
else:
    from traceback import format_exception


def raise_worker_error(mode: str) -> None:
    if mode == "group":
        try:
            raise_worker_error("plain")
        except ValueError as exc:
            raise ExceptionGroup(
                "worker group", [exc, TypeError("other error")]
            ) from None

    try:
        raise KeyError("original worker error")
    except KeyError as cause:
        error = ValueError("worker error")
        if mode == "cause":
            raise error from cause
        elif mode == "context":
            raise error  # noqa: B904 (exercise implicit exception chaining)
        elif mode == "suppressed":
            raise error from None

    if mode == "notes" and sys.version_info >= (3, 11):
        error.add_note("worker note")

    raise error


@pytest.mark.parametrize(
    "mode",
    [
        "plain",
        "cause",
        "context",
        "suppressed",
        "group",
        pytest.param(
            "notes",
            marks=pytest.mark.skipif(
                sys.version_info < (3, 11), reason="notes require Python 3.11"
            ),
        ),
    ],
)
async def test_worker_traceback(mode: str) -> None:
    expected = ExceptionGroup if mode == "group" else ValueError
    with pytest.raises(expected) as caught:
        await to_process.run_sync(raise_worker_error, mode)

    error = caught.value
    assert type(error) is expected
    assert error.__cause__ is not None
    remote = str(error.__cause__)
    assert "in raise_worker_error" in remote
    assert "test_to_process.py" in remote
    assert "worker error" in remote
    assert ("original worker error" in remote) == (mode in ("cause", "context"))
    if mode == "group":
        assert isinstance(error, ExceptionGroup)
        assert error.message == "worker group"
        assert [type(exc) for exc in error.exceptions] == [ValueError, TypeError]
        assert [exc.args for exc in error.exceptions] == [
            ("worker error",),
            ("other error",),
        ]
    else:
        assert error.args == ("worker error",)

    if mode == "notes" and sys.version_info >= (3, 11):
        assert error.__notes__ == ["worker note"]
        assert "worker note" in remote

    assert remote in "".join(format_exception(error))


class UnpicklableError(Exception):
    def __reduce__(self) -> NoReturn:
        raise TypeError("cannot pickle worker error")


def unpicklable_worker_result(raise_error: bool) -> object:
    if raise_error:
        raise UnpicklableError("worker error")

    return lambda: None


@pytest.mark.parametrize("raise_error", [False, True])
async def test_worker_traceback_pickle_failure(raise_error: bool) -> None:
    # Pickling a local function raises different errors across Python runtimes.
    expected = TypeError if raise_error else (AttributeError, pickle.PicklingError)
    pid = await to_process.run_sync(os.getpid)
    with pytest.raises(expected) as caught:
        await to_process.run_sync(unpicklable_worker_result, raise_error)

    assert caught.value.__cause__ is not None
    assert "in process_worker" in str(caught.value.__cause__)
    assert "pickle.dumps" in str(caught.value.__cause__)
    assert await to_process.run_sync(os.getpid) == pid


class CausePreservingError(Exception):
    def __reduce__(self) -> tuple[object, ...]:
        return rebuild_cause_preserving_error, (self.args, self.__cause__)


def rebuild_cause_preserving_error(
    args: tuple[object, ...], cause: BaseException | None
) -> CausePreservingError:
    error = CausePreservingError(*args)
    error.__cause__ = cause
    return error


def raise_cause_preserving_error() -> NoReturn:
    raise CausePreservingError("worker error") from KeyError("preserved cause")


async def test_worker_preserves_custom_pickled_cause() -> None:
    with pytest.raises(CausePreservingError) as caught:
        await to_process.run_sync(raise_cause_preserving_error)

    assert caught.value.args == ("worker error",)
    assert type(caught.value.__cause__) is KeyError
    assert caught.value.__cause__.args == ("preserved cause",)


def raise_worker_base_exception(exception_type: type[BaseException]) -> NoReturn:
    raise exception_type("worker base error")


@pytest.mark.parametrize("exception_type", [SystemExit, KeyboardInterrupt])
async def test_worker_traceback_base_exception(
    exception_type: type[BaseException],
) -> None:
    with pytest.raises(exception_type) as caught:
        await to_process.run_sync(raise_worker_base_exception, exception_type)

    assert caught.value.args == ("worker base error",)
    assert "in raise_worker_base_exception" in str(caught.value.__cause__)


async def test_worker_initialization_traceback(
    monkeypatch: MonkeyPatch, mocker: MockerFixture, tmp_path: Path
) -> None:
    script = tmp_path / "failing_main.py"
    script.write_text("raise ValueError('worker initialization failed')\n")
    monkeypatch.setattr("__main__.__file__", str(script))
    opened = mocker.spy(to_process, "open_process")
    try:
        with pytest.raises(
            BrokenWorkerProcess, match="Error during worker process"
        ) as caught:
            await to_process.run_sync(os.getpid)
    finally:
        # Failed initialization does not register the process for pool cleanup.
        await opened.spy_return.aclose()

    error = caught.value.__cause__
    assert type(error) is ValueError
    assert error.args == ("worker initialization failed",)
    assert "failing_main.py" in str(error.__cause__)


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


def _flood_stderr() -> str:
    """Helper that writes enough data to stderr to fill an undrained pipe buffer."""

    # A typical pipe buffer is 64 KiB; write well beyond that to ensure it would block
    # if stderr were still connected to the (undrained) parent pipe.
    payload = "x" * (1024 * 1024)
    for stream in sys.stdout, sys.stderr:
        stream.write(payload)
        stream.flush()

    return "completed"


async def test_stderr_flood() -> None:
    """
    Test that writing large amounts of data to stderr in the worker process won't
    deadlock the call. Regression test for the worker's stderr not being redirected to
    /dev/null, leaving it connected to an undrained pipe.
    """

    with fail_after(10):
        assert await to_process.run_sync(_flood_stderr) == "completed"


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


def _check_main_importable() -> int:
    """Helper that runs in the worker process to check main was imported correctly"""

    # python multiprocessing does it this way and there is probably code dependent on it.
    assert sys.modules["__main__"] == sys.modules["__mp_main__"]

    return sys.modules["__main__"].foo


async def test_entrypoint_main_module(monkeypatch: MonkeyPatch, tmp_path: Path) -> None:
    """
    Test that worker process creation succeeds when __main__.__file__ points to an
    entry point script (no .py extension). Regression test for #1027.
    """

    script_path = tmp_path / "my-entrypoint"
    script_path.write_text("foo=3")
    monkeypatch.setattr("__main__.__file__", str(script_path))
    assert await to_process.run_sync(_check_main_importable) == 3
