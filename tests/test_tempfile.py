from __future__ import annotations

import os
import pathlib
import shutil
import tempfile

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

pytestmark = pytest.mark.anyio


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
            assert os.path.exists(filename)

            await af.write(data)
            await af.seek(0)
            assert await af.read() == data

        assert not os.path.exists(filename)

    async def test_exception_handling(self) -> None:
        async with NamedTemporaryFile[bytes]() as af:
            filename = af.name
            assert os.path.exists(filename)

        assert not os.path.exists(filename)

        with pytest.raises(ValueError):
            await af.write(b"should fail")


class TestSpooledTemporaryFile:
    async def test_io_and_rollover(self) -> None:
        data = b"spooled temporary file data" * 3
        async with SpooledTemporaryFile[bytes](max_size=10) as stf:
            await stf.write(data)
            await stf.seek(0)
            assert await stf.read() == data

            pos = await stf.tell()
            assert isinstance(pos, int)

            await stf.rollover()
            assert not stf.closed

        assert stf.closed

    async def test_rollover_handling(self) -> None:
        async with SpooledTemporaryFile[bytes](max_size=10) as stf:
            await stf.write(b"1234567890")
            await stf.rollover()
            assert not stf.closed

            await stf.write(b"more data")
            await stf.seek(0)
            result = await stf.read()

            assert result == b"1234567890more data"

    async def test_write_without_rolled(self) -> None:
        async with SpooledTemporaryFile[bytes](max_size=10) as stf:
            stf._fp._rolled = False
            stf._fp._max_size = 10
            rollover_called = False
            original_rollover = stf._fp.rollover

            def fake_rollover() -> None:
                nonlocal rollover_called
                rollover_called = True
                return original_rollover()

            stf._fp.rollover = fake_rollover
            n1 = await stf.write(b"12345")
            assert n1 == 5
            assert not rollover_called
            await stf.write(b"67890X")
            assert rollover_called

    async def test_writelines_without_rolled(self) -> None:
        async with SpooledTemporaryFile[bytes](max_size=20) as stf:
            stf._fp._rolled = False
            stf._fp._max_size = 20
            rollover_called = False
            original_rollover = stf._fp.rollover

            def fake_rollover() -> None:
                nonlocal rollover_called
                rollover_called = True
                return original_rollover()

            stf._fp.rollover = fake_rollover
            await stf.writelines([b"hello", b"world"])
            await stf.seek(0)

            content = await stf.read()
            assert content == b"helloworld"

            await stf.writelines([b"1234567890123456"])
            assert rollover_called

    async def test_closed_state(self) -> None:
        async with SpooledTemporaryFile[bytes](max_size=10) as stf:
            assert not stf.closed

        assert stf.closed


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


async def test_mkstemp() -> None:
    fd, path = await mkstemp(suffix=".txt", prefix="mkstemp_", text=True)
    assert isinstance(fd, int)
    assert isinstance(path, str)

    with os.fdopen(fd, "w", encoding="utf-8") as f:
        f.write("mkstemp")

    with open(path, encoding="utf-8") as f:
        content = f.read()

    assert content == "mkstemp"

    os.remove(path)


async def test_mkdtemp() -> None:
    d = await mkdtemp(prefix="mkdtemp_")

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
