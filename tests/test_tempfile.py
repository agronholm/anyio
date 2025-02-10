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
    gettempprefix,
    gettempprefixb,
    mkdtemp,
    mkstemp,
    to_thread,
)

pytestmark = pytest.mark.anyio


@pytest.mark.anyio
async def test_temporary_file() -> None:
    data = b"temporary file data"
    async with TemporaryFile[bytes]() as af:
        await af.write(data)
        await af.seek(0)
        result = await af.read()
    assert result == data
    assert af.closed


@pytest.mark.anyio
async def test_named_temporary_file() -> None:
    data = b"named temporary file data"
    async with NamedTemporaryFile[bytes]() as af:
        filename: str = str(af.name)
        assert os.path.exists(filename)
        await af.write(data)
        await af.seek(0)
        result = await af.read()
    assert result == data
    assert not os.path.exists(filename)


@pytest.mark.anyio
async def test_spooled_temporary_file_io_and_rollover() -> None:
    data = b"spooled temporary file data" * 3
    async with SpooledTemporaryFile[bytes](max_size=10) as stf:
        await stf.write(data)
        await stf.seek(0)
        result = await stf.read()
        assert result == data
        pos = await stf.tell()
        assert isinstance(pos, int)
        await stf.rollover()
        assert not stf.closed
    assert stf.closed


@pytest.mark.anyio
async def test_spooled_temporary_file_error_conditions() -> None:
    stf = SpooledTemporaryFile[bytes]()
    with pytest.raises(RuntimeError):
        await stf.rollover()
    with pytest.raises(AttributeError):
        _ = stf.nonexistent_attribute


@pytest.mark.anyio
async def test_temporary_directory_context_manager() -> None:
    async with TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        assert td_path.exists() and td_path.is_dir()
        file_path = td_path / "test.txt"
        file_path.write_text("temp dir test", encoding="utf-8")
        assert file_path.exists()
    assert not td_path.exists()


@pytest.mark.anyio
async def test_temporary_directory_cleanup_method() -> None:
    td = TemporaryDirectory()
    td_str = await td.__aenter__()
    td_path = pathlib.Path(td_str)
    file_path = td_path / "file.txt"
    file_path.write_text("cleanup test", encoding="utf-8")
    await td.cleanup()
    assert not td_path.exists()


@pytest.mark.anyio
async def test_mkstemp() -> None:
    fd, path_ = await mkstemp(suffix=".txt", prefix="mkstemp_", text=True)
    assert isinstance(fd, int)
    assert isinstance(path_, str)

    def write_file() -> None:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            f.write("mkstemp")

    await to_thread.run_sync(write_file)

    def read_file() -> str:
        with open(path_, encoding="utf-8") as f:
            return f.read()

    content = await to_thread.run_sync(read_file)
    assert content == "mkstemp"
    await to_thread.run_sync(lambda: os.remove(path_))


@pytest.mark.anyio
async def test_mkdtemp() -> None:
    d = await mkdtemp(prefix="mkdtemp_")
    if isinstance(d, bytes):
        dp = pathlib.Path(os.fsdecode(d))
    else:
        dp = pathlib.Path(d)
    assert dp.exists() and dp.is_dir()
    await to_thread.run_sync(lambda: shutil.rmtree(dp))
    assert not dp.exists()


@pytest.mark.anyio
async def test_gettemp_functions() -> None:
    pref = await gettempprefix()
    prefb = await gettempprefixb()
    tdir = await gettempdir()
    tdirb = await gettempdirb()
    assert isinstance(pref, str)
    assert isinstance(prefb, bytes)
    assert isinstance(tdir, str)
    assert isinstance(tdirb, bytes)
    assert pref == tempfile.gettempprefix()
    assert prefb == tempfile.gettempprefixb()
    assert tdir == tempfile.gettempdir()
    assert tdirb == tempfile.gettempdirb()


@pytest.mark.anyio
async def test_named_temporary_file_exception_handling() -> None:
    async with NamedTemporaryFile[bytes]() as af:
        filename = str(af.name)
        assert os.path.exists(filename)

    assert not os.path.exists(filename)
    with pytest.raises(ValueError):
        await af.write(b"should fail")


@pytest.mark.anyio
async def test_temporary_directory_exception_handling() -> None:
    async with TemporaryDirectory() as td:
        td_path = pathlib.Path(td)
        assert td_path.exists() and td_path.is_dir()

    assert not td_path.exists()
    with pytest.raises(FileNotFoundError):
        (td_path / "nonexistent.txt").write_text("should fail", encoding="utf-8")


@pytest.mark.anyio
async def test_spooled_temporary_file_rollover_handling() -> None:
    async with SpooledTemporaryFile[bytes](max_size=10) as stf:
        await stf.write(b"1234567890")
        await stf.rollover()
        assert not stf.closed
        await stf.write(b"more data")
        await stf.seek(0)
        result = await stf.read()
        assert result == b"1234567890more data"


@pytest.mark.anyio
async def test_spooled_temporary_file_closed_state() -> None:
    async with SpooledTemporaryFile[bytes](max_size=10) as stf:
        assert not stf.closed

    assert stf.closed
