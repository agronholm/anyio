from __future__ import annotations

import errno
import io
import os
import pathlib
import sys
import threading
from contextvars import ContextVar
from types import SimpleNamespace
from typing import Any
from unittest.mock import patch

import pytest

from anyio import (
    CancelScope,
    CapacityLimiter,
    Event,
    Path,
    TemporaryFile,
    create_task_group,
    from_thread,
    open_file,
    to_thread,
    wait_all_tasks_blocked,
    wrap_file,
)
from anyio._core import _fileio


@pytest.fixture(
    params=[
        pytest.param(("emscripten", False), id="emscripten-no-pthreads"),
        pytest.param((sys.platform, None), id="desktop"),
        pytest.param(("emscripten", True), id="emscripten-pthreads"),
        pytest.param(("emscripten", None), id="emscripten-capability-unknown"),
    ]
)
def simulated_fileio_sys(
    monkeypatch: pytest.MonkeyPatch, request: pytest.FixtureRequest
) -> bool:
    platform_name, pthreads = request.param
    attrs = vars(sys).copy()
    attrs.pop("_emscripten_info", None)
    attrs["platform"] = platform_name
    if pthreads is not None:
        attrs["_emscripten_info"] = SimpleNamespace(pthreads=pthreads)

    monkeypatch.setattr(_fileio, "sys", SimpleNamespace(**attrs))
    return platform_name == "emscripten" and pthreads is False


def _assert_callback_thread(
    callback_threads: list[int], caller_thread: int, inline: bool
) -> None:
    assert len(callback_threads) == 1
    if inline:
        assert callback_threads[0] == caller_thread
    else:
        assert callback_threads[0] != caller_thread


async def test_asyncfile_callback_thread_policy(
    simulated_fileio_sys: bool, deactivate_blockbuster: None
) -> None:
    callback_threads: list[int] = []
    caller_thread = threading.get_ident()

    class RecordingFile(io.StringIO):
        def read(self, size: int | None = -1) -> str:
            callback_threads.append(threading.get_ident())
            return super().read(size)

    wrapped = wrap_file(RecordingFile("payload"))
    try:
        assert await wrapped.read() == "payload"
    finally:
        await wrapped.aclose()

    _assert_callback_thread(callback_threads, caller_thread, simulated_fileio_sys)


@pytest.mark.parametrize("explicit_limiter", [False, True], ids=["default", "explicit"])
async def test_cancelled_limiter_waiter_never_calls_file(
    simulated_fileio_sys: bool,
    explicit_limiter: bool,
    deactivate_blockbuster: None,
) -> None:
    if explicit_limiter:
        limiter = CapacityLimiter(1)
        wrapped_limiter = limiter
    else:
        limiter = to_thread.current_default_thread_limiter()
        wrapped_limiter = None

    original_total_tokens = limiter.total_tokens
    if not explicit_limiter:
        limiter.total_tokens = 1

    callback_threads: list[int] = []
    done = Event()
    waiter_scope: CancelScope | None = None

    class RecordingFile(io.StringIO):
        def read(self, size: int | None = -1) -> str:
            callback_threads.append(threading.get_ident())
            return super().read(size)

    wrapped = wrap_file(RecordingFile("payload"), limiter=wrapped_limiter)
    assert wrapped.limiter is wrapped_limiter

    await limiter.acquire()
    try:

        async def waiting_read() -> None:
            nonlocal waiter_scope
            with CancelScope() as scope:
                waiter_scope = scope
                try:
                    await wrapped.read()
                finally:
                    done.set()

        async with create_task_group() as tg:
            tg.start_soon(waiting_read)
            await wait_all_tasks_blocked()
            assert waiter_scope is not None
            waiter_scope.cancel()
            await done.wait()
    finally:
        limiter.release()
        if not explicit_limiter:
            limiter.total_tokens = original_total_tokens
    await wrapped.aclose()

    assert callback_threads == []
    assert limiter.borrowed_tokens == 0


async def test_callback_exception_releases_limiter(
    simulated_fileio_sys: bool, deactivate_blockbuster: None
) -> None:
    limiter = CapacityLimiter(1)

    class RaisingFile(io.StringIO):
        def read(self, size: int | None = -1) -> str:
            raise ValueError("callback failed")

    wrapped = wrap_file(RaisingFile("payload"), limiter=limiter)
    try:
        with pytest.raises(ValueError, match="callback failed"):
            await wrapped.read()
    finally:
        await wrapped.aclose()

    assert limiter.borrowed_tokens == 0
    followup = wrap_file(io.StringIO("followup"), limiter=limiter)
    try:
        assert await followup.read() == "followup"
    finally:
        await followup.aclose()


async def test_cancelled_aclose_is_shielded(
    simulated_fileio_sys: bool, deactivate_blockbuster: None
) -> None:
    wrapped = wrap_file(io.StringIO("payload"))
    with CancelScope() as scope:
        scope.cancel()
        await wrapped.aclose()

    assert wrapped.closed


async def test_open_file_opener_args_and_synchronous_cancel(
    simulated_fileio_sys: bool, deactivate_blockbuster: None, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "opened.txt"
    path.write_text("payload", encoding="utf-8")
    caller_thread = threading.get_ident()
    opener_calls: list[tuple[str, int, int]] = []
    opened_fds: list[int] = []
    cancel_scope = CancelScope()

    def opener(filename: str, flags: int) -> int:
        if threading.get_ident() == caller_thread:
            cancel_scope.cancel()
        else:
            from_thread.run_sync(cancel_scope.cancel)

        fd = os.open(filename, flags)
        opener_calls.append((filename, flags, threading.get_ident()))
        opened_fds.append(fd)
        return fd

    wrapped = None
    try:
        with cancel_scope:
            wrapped = await open_file(str(path), opener=opener)

        assert len(opener_calls) == 1
        assert (opener_calls[0][1] & os.O_ACCMODE) == os.O_RDONLY
        _assert_callback_thread(
            [opener_calls[0][2]], caller_thread, simulated_fileio_sys
        )
        assert opener_calls[0][0] == str(path)
        assert isinstance(opener_calls[0][1], int)
        assert wrapped is not None
        assert wrapped.wrapped.fileno() == opened_fds[0]
    finally:
        if wrapped is not None:
            await wrapped.aclose()
        elif opened_fds:
            try:
                os.close(opened_fds[0])
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise


async def test_file_callback_context_isolation(
    simulated_fileio_sys: bool, deactivate_blockbuster: None
) -> None:
    callback_context: ContextVar[str] = ContextVar("callback_context", default="unset")
    callback_seen: list[str] = []
    token = callback_context.set("caller")

    class MutatingFile(io.StringIO):
        def read(self, size: int | None = -1) -> str:
            callback_seen.append(callback_context.get())
            callback_context.set("callback")
            return super().read(size)

    wrapped = wrap_file(MutatingFile("payload"))
    try:
        assert await wrapped.read() == "payload"
        assert callback_seen == ["caller"]
        assert callback_context.get() == "caller"
    finally:
        try:
            await wrapped.aclose()
        finally:
            callback_context.reset(token)


async def test_invalid_limiter_stays_type_error(
    simulated_fileio_sys: bool, deactivate_blockbuster: None, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "opened.txt"
    path.write_text("payload", encoding="utf-8")
    with pytest.raises(TypeError, match="limiter must be"):
        wrap_file(io.StringIO(), limiter=object())  # type: ignore[arg-type]

    opener_calls: list[tuple[str, int]] = []
    opened_fds: list[int] = []

    def opener(filename: str, flags: int) -> int:
        opener_calls.append((filename, flags))
        fd = os.open(filename, flags)
        opened_fds.append(fd)
        return fd

    try:
        with pytest.raises((TypeError, AttributeError)):
            await open_file(path, opener=opener, limiter=object())  # type: ignore[call-overload]
    finally:
        for fd in opened_fds:
            try:
                os.close(fd)
            except OSError as exc:
                if exc.errno != errno.EBADF:
                    raise

    assert opener_calls == []


async def test_path_open_remains_threaded_on_native(
    simulated_fileio_sys: bool, deactivate_blockbuster: None, tmp_path: pathlib.Path
) -> None:
    path = tmp_path / "path-open.txt"
    caller_thread = threading.get_ident()
    callback_threads: list[int] = []
    path_type = type(path)
    original_open = path_type.open

    def recording_open(self: pathlib.Path, *args: Any, **kwargs: Any) -> Any:
        callback_threads.append(threading.get_ident())
        return original_open(self, *args, **kwargs)

    with patch.object(path_type, "open", recording_open):
        async with await Path(path).open("w") as wrapped:
            await wrapped.write("native")

    assert callback_threads and callback_threads[0] != caller_thread


async def test_native_threaded_controls(
    simulated_fileio_sys: bool, deactivate_blockbuster: None, tmp_path: pathlib.Path
) -> None:
    caller_thread = threading.get_ident()
    assert await to_thread.run_sync(threading.get_ident) != caller_thread

    path = tmp_path / "native-controls.txt"
    path.write_text("native", encoding="utf-8")
    path_type = type(path)
    callback_threads: list[int] = []
    original_exists = path_type.exists
    original_read_text = path_type.read_text

    def recording_exists(self: pathlib.Path, *args: Any, **kwargs: Any) -> bool:
        callback_threads.append(threading.get_ident())
        return original_exists(self, *args, **kwargs)

    def recording_read_text(self: pathlib.Path, *args: Any, **kwargs: Any) -> str:
        callback_threads.append(threading.get_ident())
        return original_read_text(self, *args, **kwargs)

    with (
        patch.object(path_type, "exists", recording_exists),
        patch.object(path_type, "read_text", recording_read_text),
    ):
        async_path = Path(path)
        assert await async_path.exists()
        assert await async_path.read_text() == "native"

    assert len(callback_threads) == 2
    assert all(thread_id != caller_thread for thread_id in callback_threads)

    async with TemporaryFile[bytes]() as wrapped:
        await wrapped.write(b"native")
        await wrapped.seek(0)
        assert await wrapped.read() == b"native"
