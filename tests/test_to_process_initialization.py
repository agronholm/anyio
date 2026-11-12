from __future__ import annotations

import os
import sys
from collections.abc import Sequence
from contextlib import suppress
from pathlib import Path
from typing import TYPE_CHECKING, Any

import pytest
from pytest import MonkeyPatch

from anyio import (
    BrokenWorkerProcess,
    CancelScope,
    ClosedResourceError,
    EndOfStream,
    open_process,
    to_process,
)

if TYPE_CHECKING:
    from anyio.abc import Process


async def assert_closed(process: Process) -> None:
    # Check completion before any further checkpoint can reap the child.
    assert process.returncode is not None
    assert process.stdin is not None
    assert process.stdout is not None
    with pytest.raises(ClosedResourceError):
        await process.stdin.send(b"unused")
    with pytest.raises(ClosedResourceError):
        await process.stdout.receive()


async def cleanup(processes: list[Process]) -> None:
    # Also reap children when testing against the broken implementation.
    for process in processes:
        if process.returncode is None:
            with suppress(ProcessLookupError):
                process.kill()
        await process.aclose()


@pytest.mark.parametrize(
    "failure", ["init_error", "bad_ready", "early_exit", "init_response", "kill_race"]
)
async def test_initialization_failure_closes_process(
    monkeypatch: MonkeyPatch, tmp_path: Path, failure: str
) -> None:
    original_open = open_process
    processes: list[Process] = []
    script = tmp_path / "bad_main.py"
    script.write_text("raise ValueError('initialization marker')\n")

    async def open_worker(command: Sequence[str], **kwargs: Any) -> Process:
        if failure == "bad_ready":
            command = [
                sys.executable,
                "-u",
                "-c",
                (
                    "import sys; sys.stdout.buffer.write(b'BROKEN\\n'); "
                    "sys.stdin.buffer.read()"
                ),
            ]
        elif failure == "early_exit":
            command = [sys.executable, "-c", "pass"]
        elif failure == "init_response":
            command = [
                sys.executable,
                "-u",
                "-c",
                (
                    "import pickle, sys; sys.stdout.buffer.write(b'READY\\n'); "
                    "pickle.load(sys.stdin.buffer); "
                    "sys.stdout.buffer.write(b'BROKEN\\n'); "
                    "sys.stdin.buffer.read()"
                ),
            ]

        process = await original_open(command, **kwargs)
        processes.append(process)
        if failure == "early_exit":
            await process.wait()
        elif failure == "kill_race":
            original_kill = process.kill

            def kill_then_report_exit() -> None:
                original_kill()
                raise ProcessLookupError

            monkeypatch.setattr(process, "kill", kill_then_report_exit)

        return process

    try:
        with monkeypatch.context() as patch:
            patch.setattr(to_process, "open_process", open_worker)
            if failure in ("init_error", "kill_race"):
                patch.setattr("__main__.__file__", str(script))

            with pytest.raises(BrokenWorkerProcess) as caught:
                await to_process.run_sync(os.getpid)

        process = processes[0]
        await assert_closed(process)
        if failure in ("init_error", "kill_race"):
            assert isinstance(caught.value.__cause__, ValueError)
            assert str(caught.value.__cause__) == "initialization marker"
        elif failure == "bad_ready":
            assert str(caught.value).startswith("Worker process returned unexpected")
            assert caught.value.__cause__ is None
        elif failure == "early_exit":
            assert isinstance(caught.value.__cause__, EndOfStream)
        elif failure == "init_response":
            assert caught.value.args == ()
            assert isinstance(caught.value.__cause__, ValueError)

        assert await to_process.run_sync(os.getpid) != process.pid
    finally:
        await cleanup(processes)


async def test_cancel_during_startup_closes_process(monkeypatch: MonkeyPatch) -> None:
    original_open = open_process
    processes: list[Process] = []
    scope = CancelScope()

    async def open_worker(command: Sequence[str], **kwargs: Any) -> Process:
        # Hold the real child before READY so cancellation reaches initialization,
        # rather than the command exchange which already cleans up on failure.
        process = await original_open(
            [sys.executable, "-c", "import sys; sys.stdin.buffer.read()"], **kwargs
        )
        processes.append(process)
        scope.cancel()
        return process

    try:
        with monkeypatch.context() as patch:
            patch.setattr(to_process, "open_process", open_worker)
            with scope:
                await to_process.run_sync(os.getpid)

        assert scope.cancelled_caught
        process = processes[0]
        await assert_closed(process)
        assert await to_process.run_sync(os.getpid) != process.pid
    finally:
        await cleanup(processes)
