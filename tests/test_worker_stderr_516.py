from __future__ import annotations

import asyncio
import logging
import os
import sys
import time
from pathlib import Path
from typing import Any

import psutil
import pytest

import anyio
from anyio import (
    CancelScope,
    CapacityLimiter,
    create_task_group,
    fail_after,
    to_process,
)

MARKER = "ANYIO516_WORKER_STDERR"


def _emit_logs(gate: str) -> dict[str, Any]:
    pid = os.getpid()
    # Intentional worker stdout observation for issue 516.
    print(f"{MARKER}:stdout", flush=True)  # noqa: T201
    # Intentional worker stderr observation for issue 516.
    print(f"{MARKER}:print", file=sys.stderr, flush=True)  # noqa: T201
    logger = logging.getLogger(MARKER)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(message)s"))
    logger.addHandler(handler)
    logger.setLevel(logging.WARNING)
    try:
        logger.warning("%s:logging", MARKER)
        handler.flush()
    finally:
        logger.removeHandler(handler)
        handler.close()
    ready = Path(gate).with_suffix(".ready")
    release = Path(gate).with_suffix(".release")
    ready.write_text(str(pid))
    deadline = time.monotonic() + 5
    while not release.exists():
        if time.monotonic() >= deadline:
            raise TimeoutError("release handshake timed out")
        time.sleep(0.005)
    return {"protocol": "return", "pid": pid}


def _pid_sleep(seconds: float) -> int:
    pid = os.getpid()
    time.sleep(seconds)
    return pid


def _private_flag_is_hidden() -> bool:
    return "--_anyio_inherit_stderr" not in sys.argv


def _signal_and_sleep(suffix: str, seconds: float) -> int:
    pid = os.getpid()
    # Intentional worker stderr observation for issue 516.
    print(f"{MARKER}:{suffix}:pid={pid}", file=sys.stderr, flush=True)  # noqa: T201
    time.sleep(seconds)
    return pid


def _write_pid_and_sleep(path: str, seconds: float) -> int:
    pid = os.getpid()
    Path(path).write_text(str(pid))
    time.sleep(seconds)
    return pid


def _pid_exists(pid: int) -> bool:
    return psutil.pid_exists(pid)


@pytest.mark.anyio
async def test_inherit_stderr_print_and_logging_arrive_before_release(
    capfd: pytest.CaptureFixture[str], tmp_path: Path
) -> None:
    gate = tmp_path / "call"
    done = anyio.Event()
    result_box: dict[str, Any] = {}
    captured_out = ""
    captured_err = ""

    async def invoke() -> None:
        try:
            result_box["result"] = await to_process.run_sync(
                _emit_logs, str(gate), inherit_stderr=True
            )
        finally:
            done.set()

    async with create_task_group() as tg:
        tg.start_soon(invoke)
        for _ in range(500):
            await anyio.sleep(0.01)
            out, err = capfd.readouterr()
            captured_out += out
            captured_err += err
            if (
                gate.with_suffix(".ready").exists()
                and f"{MARKER}:print" in captured_err
                and f"{MARKER}:logging" in captured_err
            ):
                assert not done.is_set()
                gate.with_suffix(".release").write_text("release")
                break
        else:
            pytest.fail(
                "worker did not complete the deterministic stderr arrival handshake"
            )

    out, err = capfd.readouterr()
    captured_out += out
    captured_err += err
    assert result_box["result"]["protocol"] == "return"
    assert f"{MARKER}:stdout" not in captured_out
    assert f"{MARKER}:print" in captured_err
    assert f"{MARKER}:logging" in captured_err


@pytest.mark.anyio
async def test_inherit_stderr_mode_keyed_pool_reuse() -> None:
    assert await to_process.run_sync(_private_flag_is_hidden, inherit_stderr=True)
    default_pid_1 = await to_process.run_sync(_pid_sleep, 0.01)
    stderr_pid_1 = await to_process.run_sync(_pid_sleep, 0.01, inherit_stderr=True)
    stderr_pid_2 = await to_process.run_sync(_pid_sleep, 0.01, inherit_stderr=True)
    default_pid_2 = await to_process.run_sync(_pid_sleep, 0.01)
    assert default_pid_1 == default_pid_2
    assert stderr_pid_1 == stderr_pid_2
    assert default_pid_1 != stderr_pid_1


@pytest.mark.anyio
@pytest.mark.usefixtures("deactivate_blockbuster")
async def test_inherit_stderr_cancellation_starts_reaps_and_replaces_worker(
    capfd: pytest.CaptureFixture[str],
) -> None:
    result_box: dict[str, Any] = {}
    captured = ""

    async def invoke() -> None:
        try:
            result_box["result"] = await to_process.run_sync(
                _signal_and_sleep, "cancel", 10, cancellable=True, inherit_stderr=True
            )
        except BaseException as exc:
            result_box["error_type"] = type(exc).__name__

    async with create_task_group() as tg:
        tg.start_soon(invoke)
        for _ in range(500):
            await anyio.sleep(0.01)
            captured += capfd.readouterr().err
            marker = f"{MARKER}:cancel:pid="
            if marker in captured:
                cancelled_pid = int(captured.split(marker, 1)[1].splitlines()[0])
                tg.cancel_scope.cancel()
                break
        else:
            pytest.fail("worker did not start before cancellation")
    replacement_pid = await to_process.run_sync(_pid_sleep, 0.01, inherit_stderr=True)
    assert isinstance(cancelled_pid, int)
    assert result_box["error_type"] in {"CancelledError", "Cancelled"}
    assert isinstance(replacement_pid, int) and replacement_pid != cancelled_pid
    assert not _pid_exists(cancelled_pid)


@pytest.mark.anyio
async def test_inherit_stderr_cancellation_before_start_does_not_start_worker(
    capfd: pytest.CaptureFixture[str],
) -> None:
    with CancelScope() as scope:
        scope.cancel()
        with pytest.raises((anyio.get_cancelled_exc_class(), asyncio.CancelledError)):
            await to_process.run_sync(
                _signal_and_sleep,
                "cancel-before-start",
                0.1,
                cancellable=True,
                inherit_stderr=True,
            )
    captured = capfd.readouterr()
    assert f"{MARKER}:cancel-before-start:pid=" not in captured.out + captured.err


@pytest.mark.anyio
async def test_inherit_stderr_idle_prune_reuses_one_and_prunes_another() -> None:
    default_limiter = CapacityLimiter(2)
    stderr_limiter = CapacityLimiter(2)
    initial: dict[str, list[int]] = {"default": [], "stderr": []}

    async def run_one(mode: str) -> None:
        limiter = default_limiter if mode == "default" else stderr_limiter
        kwargs: dict[str, Any] = {"limiter": limiter}
        if mode == "stderr":
            kwargs["inherit_stderr"] = True
        initial[mode].append(await to_process.run_sync(_pid_sleep, 0.05, **kwargs))

    async with create_task_group() as tg:
        for mode in ("default", "default", "stderr", "stderr"):
            tg.start_soon(run_one, mode)
    assert all(len(pids) == 2 and pids[0] != pids[1] for pids in initial.values())
    old_threshold = to_process.WORKER_MAX_IDLE_TIME
    try:
        to_process.WORKER_MAX_IDLE_TIME = 0
        default_reused = await to_process.run_sync(
            _pid_sleep, 0.01, limiter=default_limiter
        )
        stderr_reused = await to_process.run_sync(
            _pid_sleep, 0.01, inherit_stderr=True, limiter=stderr_limiter
        )
    finally:
        to_process.WORKER_MAX_IDLE_TIME = old_threshold
    default_pruned = next(pid for pid in initial["default"] if pid != default_reused)
    stderr_pruned = next(pid for pid in initial["stderr"] if pid != stderr_reused)
    for _ in range(200):
        if not _pid_exists(default_pruned) and not _pid_exists(stderr_pruned):
            break
        await anyio.sleep(0.01)
    assert default_reused in initial["default"]
    assert stderr_reused in initial["stderr"]
    assert not _pid_exists(default_pruned)
    assert not _pid_exists(stderr_pruned)


def _wait_reaped(pid: int) -> None:
    for _ in range(200):
        if not _pid_exists(pid):
            return
        time.sleep(0.01)
    assert not _pid_exists(pid)


@pytest.mark.parametrize("anyio_backend", ["asyncio", "trio"])
@pytest.mark.usefixtures("deactivate_blockbuster")
def test_inherit_stderr_normal_and_abnormal_or_failure_shutdown(
    anyio_backend: str, tmp_path: Path
) -> None:
    normal_paths = [tmp_path / "normal-default.pid", tmp_path / "normal-stderr.pid"]

    async def normal_body() -> tuple[int, int]:
        default_pid = await to_process.run_sync(
            _write_pid_and_sleep, str(normal_paths[0]), 0.01
        )
        stderr_pid = await to_process.run_sync(
            _write_pid_and_sleep, str(normal_paths[1]), 0.01, inherit_stderr=True
        )
        return default_pid, stderr_pid

    normal_pids = anyio.run(normal_body, backend=anyio_backend)
    assert all(isinstance(pid, int) for pid in normal_pids)
    for pid in normal_pids:
        _wait_reaped(pid)

    forced_paths = [tmp_path / "forced-default.pid", tmp_path / "forced-stderr.pid"]
    if anyio_backend == "asyncio":
        handler_errors: list[Any] = []

        async def abnormal_body() -> tuple[int, int]:
            loop = asyncio.get_running_loop()
            loop.set_exception_handler(
                lambda _loop, context: handler_errors.append(context)
            )

            async def stop_after_both_start() -> None:
                with fail_after(3):
                    # This bounded poll is the cross-process PID-file readiness gate.
                    while not all(  # noqa: ASYNC110
                        path.exists() for path in forced_paths
                    ):
                        await anyio.sleep(0.01)
                loop.call_later(0.25, loop.stop)

            async with create_task_group() as tg:
                tg.start_soon(stop_after_both_start)
                results: dict[str, int] = {}

                async def run_default() -> None:
                    results["default"] = await to_process.run_sync(
                        _write_pid_and_sleep,
                        str(forced_paths[0]),
                        10,
                        inherit_stderr=False,
                    )

                async def run_stderr() -> None:
                    results["stderr"] = await to_process.run_sync(
                        _write_pid_and_sleep,
                        str(forced_paths[1]),
                        10,
                        inherit_stderr=True,
                    )

                tg.start_soon(run_default)
                tg.start_soon(run_stderr)
            return results["default"], results["stderr"]

        with pytest.raises(RuntimeError, match="Event loop stopped"):
            anyio.run(abnormal_body, backend="asyncio")
        assert not handler_errors
    else:

        async def failed_body() -> tuple[int, int]:
            await to_process.run_sync(
                _write_pid_and_sleep, str(forced_paths[0]), 0.01, inherit_stderr=False
            )
            await to_process.run_sync(
                _write_pid_and_sleep, str(forced_paths[1]), 0.01, inherit_stderr=True
            )
            raise RuntimeError("worker-stderr normal-failure probe")

        with pytest.raises(RuntimeError, match="normal-failure probe"):
            anyio.run(failed_body, backend="trio")
    deadline = time.monotonic() + 2
    while (
        not all(path.exists() for path in forced_paths) and time.monotonic() < deadline
    ):
        time.sleep(0.01)
    assert all(path.exists() for path in forced_paths)
    for path in forced_paths:
        _wait_reaped(int(path.read_text()))
