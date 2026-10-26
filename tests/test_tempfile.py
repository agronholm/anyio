from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
from typing import Any, AnyStr
from unittest.mock import Mock, patch

import pytest

from anyio import (
    CancelScope,
    NamedTemporaryFile,
    SpooledTemporaryFile,
    TemporaryDirectory,
    TemporaryFile,
    from_thread,
    get_cancelled_exc_class,
    gettempdir,
    gettempdirb,
    mkdtemp,
    mkstemp,
)
from anyio.lowlevel import checkpoint


class TestTemporaryFile:
    async def test_temporary_file(self) -> None:
        data = b"temporary file data"
        async with TemporaryFile[bytes]() as af:
            await af.write(data)
            await af.seek(0)
            result = await af.read()

        assert result == data
        assert af.closed


class TestNamedTemporaryFile:
    async def test_named_temporary_file(self) -> None:
        data = b"named temporary file data"
        async with NamedTemporaryFile[bytes]() as af:
            filename = af.name
            assert os.path.exists(filename)  # type: ignore[arg-type]

            await af.write(data)
            await af.seek(0)
            assert await af.read() == data

        assert not os.path.exists(filename)  # type: ignore[arg-type]

    async def test_exception_handling(self) -> None:
        async with NamedTemporaryFile[bytes]() as af:
            filename = af.name
            assert os.path.exists(filename)  # type: ignore[arg-type]

        assert not os.path.exists(filename)  # type: ignore[arg-type]

        with pytest.raises(ValueError):
            await af.write(b"should fail")


class TestSpooledTemporaryFile:
    async def test_cancelled_during_rollover(self) -> None:
        original = tempfile.TemporaryFile

        def create(**kwargs: Any) -> Any:
            from_thread.run_sync(scope.cancel)
            return original(**kwargs)

        async with SpooledTemporaryFile() as stf:
            await stf.write(b"hello world")
            await stf.seek(5)
            with CancelScope() as scope:
                with patch("anyio._core._tempfile.tempfile.TemporaryFile", create):
                    await stf.rollover()

            assert stf._rolled
            assert await stf.tell() == 5
            await stf.seek(0)
            assert await stf.read() == b"hello world"

    @pytest.mark.parametrize(
        "mode, sample1, sample2, sample3, expected",
        [
            ("w+b", b"aaaa", b"bbbbbbbb", b"cc", b"aaaabbbbbbbbcc"),
            ("w+", "aaaa", "bbbbbbbb", "cc", "aaaabbbbbbbbcc"),
        ],
    )
    async def test_rollover_failure_retains_data(
        self,
        tmp_path: pathlib.Path,
        mode: str,
        sample1: Any,
        sample2: Any,
        sample3: Any,
        expected: Any,
    ) -> None:
        missing_dir = tmp_path / "missing"
        async with SpooledTemporaryFile(
            max_size=8, mode=mode, dir=str(missing_dir)
        ) as stf:
            await stf.write(sample1)
            with pytest.raises(FileNotFoundError):
                await stf.write(sample2)

            assert not stf._rolled
            assert await stf.tell() == 12
            missing_dir.mkdir()
            await stf.write(sample3)
            assert stf._rolled
            await stf.seek(0)
            assert await stf.read() == expected

    @pytest.mark.parametrize(
        "mode, sample1, sample2",
        [
            ("w+b", b"1234", b"5678"),
            ("w+", "1234", "5678"),
        ],
    )
    async def test_rollover_failure_closes_tempfile(
        self, mode: str, sample1: Any, sample2: Any
    ) -> None:
        created_file: Any = None
        original = tempfile.TemporaryFile

        def failing_create(**kwargs: Any) -> Any:
            nonlocal created_file
            created_file = original(**kwargs)
            target = getattr(created_file, "buffer", created_file)
            target.write = Mock(side_effect=OSError("write failed"))
            return created_file

        async with SpooledTemporaryFile(max_size=5, mode=mode) as stf:
            await stf.write(sample1)
            with patch("anyio._core._tempfile.tempfile.TemporaryFile", failing_create):
                with pytest.raises(OSError, match="write failed"):
                    await stf.write(sample2)

            assert created_file is not None
            assert created_file.closed
            assert not stf._rolled

    @pytest.mark.parametrize("use_writelines", [False, True])
    async def test_default_max_size_no_rollover(self, use_writelines: bool) -> None:
        data = b"hello world"
        async with SpooledTemporaryFile() as stf:
            if use_writelines:
                await stf.writelines([b"hello", b" world"])
            else:
                assert await stf.write(data) == len(data)

            assert not stf._rolled
            await stf.seek(0)
            assert await stf.read() == data

    async def test_writewithout_rolled(self) -> None:
        rollover_called = False

        async def fake_rollover() -> None:
            nonlocal rollover_called
            rollover_called = True
            await original_rollover()

        async with SpooledTemporaryFile(max_size=10) as stf:
            original_rollover = stf.rollover
            with patch.object(stf, "rollover", fake_rollover):
                assert await stf.write(b"12345") == 5
                assert not rollover_called

                await stf.write(b"67890X")
                assert rollover_called

    async def test_writelines(self) -> None:
        rollover_called = False

        async def fake_rollover() -> None:
            nonlocal rollover_called
            rollover_called = True
            await original_rollover()

        async with SpooledTemporaryFile(max_size=20) as stf:
            original_rollover = stf.rollover
            with patch.object(stf, "rollover", fake_rollover):
                await stf.writelines([b"hello", b"world"])
                assert not rollover_called
                await stf.seek(0)

                assert await stf.read() == b"helloworld"
                await stf.writelines([b"1234567890123456"])
                assert rollover_called

    async def test_rollover_preserves_position(self) -> None:
        """Rollover preserves the position of a partially read file."""
        async with SpooledTemporaryFile[bytes](max_size=1024) as stf:
            await stf.write(b"hello world")
            await stf.seek(2)
            await stf.rollover()
            assert await stf.tell() == 2
            assert await stf.read() == b"llo world"

    async def test_closed_state(self) -> None:
        async with SpooledTemporaryFile(max_size=10) as stf:
            assert not stf.closed

        assert stf.closed

    async def test_exact_boundary_no_rollover(self) -> None:
        async with SpooledTemporaryFile(max_size=10) as stf:
            await stf.write(b"0123456789")
            assert not stf._rolled

            await stf.write(b"x")
            assert stf._rolled

    async def test_readinto(self) -> None:
        async with SpooledTemporaryFile(max_size=1024, mode="w+b") as stf:
            await stf.write(b"hello world")
            await stf.seek(0)
            buf = bytearray(5)
            assert await stf.readinto(buf) == 5
            assert bytes(buf) == b"hello"

    async def test_readinto1(self) -> None:
        async with SpooledTemporaryFile(max_size=1024, mode="w+b") as stf:
            await stf.write(b"hello world")
            await stf.seek(0)
            buf = bytearray(5)
            assert await stf.readinto1(buf) == 5
            assert bytes(buf) == b"hello"


class TestTemporaryDirectory:
    async def test_cancellation_during_creation(self) -> None:
        original = tempfile.TemporaryDirectory
        manager = TemporaryDirectory()
        paths: list[pathlib.Path] = []

        def create(**kwargs: Any) -> tempfile.TemporaryDirectory[str]:
            directory = original(**kwargs)
            paths.append(pathlib.Path(directory.name))
            from_thread.run_sync(scope.cancel)
            return directory

        with CancelScope() as scope:
            with patch("anyio._core._tempfile.tempfile.TemporaryDirectory", create):
                async with manager:
                    await checkpoint()

        try:
            assert scope.cancelled_caught
            assert len(paths) == 1
            assert not paths[0].exists()
        finally:
            await manager.cleanup()

    async def test_context_manager(self) -> None:
        async with TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            assert td_path.exists() and td_path.is_dir()

            file_path = td_path / "test.txt"
            file_path.write_text("temp dir test", encoding="utf-8")
            assert file_path.exists()

        assert not td_path.exists()

    async def test_cleanup_method(self) -> None:
        td = TemporaryDirectory()
        td_str = await td.__aenter__()
        td_path = pathlib.Path(td_str)

        file_path = td_path / "file.txt"
        file_path.write_text("cleanup test", encoding="utf-8")

        await td.cleanup()
        assert not td_path.exists()

    async def test_exception_handling(self) -> None:
        async with TemporaryDirectory() as td:
            td_path = pathlib.Path(td)
            assert td_path.exists() and td_path.is_dir()

        assert not td_path.exists()

        with pytest.raises(FileNotFoundError):
            (td_path / "nonexistent.txt").write_text("should fail", encoding="utf-8")

    async def test_exit_with_cancellation(self) -> None:
        """
        Test that the directory is cleaned up even if the host task is cancelled
        while exiting the context manager.

        ``__aexit__`` runs the synchronous cleanup in a worker thread via
        ``to_thread.run_sync``, which performs a cancellation checkpoint on entry.
        Wrapping that call in a shielded cancel scope ensures that a pending
        cancellation does not prevent the cleanup from running.
        """
        with CancelScope() as outer_scope:
            async with TemporaryDirectory() as td:
                td_path = pathlib.Path(td)
                assert td_path.exists() and td_path.is_dir()
                outer_scope.cancel()

        assert not td_path.exists()

    async def test_cleanup_method_with_cancellation(self) -> None:
        """
        Test that the ``cleanup()`` method removes the directory even if the host
        task is already cancelled when it is called, and that the pending
        cancellation is still delivered to the caller afterwards.
        """
        td = TemporaryDirectory()
        async with td as td_str:
            td_path = pathlib.Path(td_str)
            assert td_path.exists() and td_path.is_dir()
            with CancelScope() as outer_scope:
                outer_scope.cancel()
                with pytest.raises(get_cancelled_exc_class()):
                    await td.cleanup()

            assert not td_path.exists()


@pytest.mark.parametrize(
    "suffix, prefix, text, content",
    [
        (".txt", "mkstemp_", True, "mkstemp"),
        (b".txt", b"mkstemp_", False, b"mkstemp"),
    ],
)
async def test_mkstemp(
    suffix: AnyStr,
    prefix: AnyStr,
    text: bool,
    content: AnyStr,
) -> None:
    fd, path = await mkstemp(suffix=suffix, prefix=prefix, text=text)

    assert isinstance(fd, int)
    if text:
        assert isinstance(path, str)
    else:
        assert isinstance(path, bytes)

    if text:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write(content)
        with open(path, encoding="utf-8") as f:
            read_content = f.read()
    else:
        with os.fdopen(fd, "wb") as f:
            f.write(content)
        with open(os.fsdecode(path), "rb") as f:
            read_content = f.read()

    assert read_content == content

    os.remove(path)


@pytest.mark.parametrize("prefix", [b"mkdtemp_", "mkdtemp_"])
async def test_mkdtemp(prefix: AnyStr) -> None:
    d = await mkdtemp(prefix=prefix)

    if isinstance(d, bytes):
        dp = pathlib.Path(os.fsdecode(d))
    else:
        dp = pathlib.Path(d)

    assert dp.is_dir()

    shutil.rmtree(dp)


async def test_gettemp_functions() -> None:
    tdir = await gettempdir()
    tdirb = await gettempdirb()

    assert tdir == tempfile.gettempdir()
    assert tdirb == tempfile.gettempdirb()
