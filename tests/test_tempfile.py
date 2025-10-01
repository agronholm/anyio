from __future__ import annotations

import os
import pathlib
import shutil
import tempfile
from typing import AnyStr
from unittest.mock import patch

import pytest

from anyio import (
    NamedTemporaryFile,
    SpooledTemporaryFile,
    TemporaryDirectory,
    TemporaryFile,
    gettempdir,
    gettempdirb,
    mkdtemp,
    mkstemp,
)


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


class TestTemporaryDirectory:
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
