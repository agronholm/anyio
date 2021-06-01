from pathlib import PosixPath

import pytest
from _pytest.tmpdir import TempPathFactory

from anyio import open_file

pytestmark = pytest.mark.anyio


@pytest.fixture(scope='module')
def testdata() -> bytes:
    return b''.join(bytes([i] * 1000) for i in range(10))


@pytest.fixture
def testdatafile(tmp_path_factory: TempPathFactory, testdata: bytes) -> PosixPath:
    file = tmp_path_factory.mktemp('file').joinpath('testdata')
    file.write_bytes(testdata)
    return file


async def test_open_close(testdatafile: PosixPath) -> None:
    f = await open_file(testdatafile)
    await f.aclose()


async def test_read(testdatafile: PosixPath, testdata: bytes) -> None:
    async with await open_file(testdatafile, 'rb') as f:
        data = await f.read()

    assert f.closed
    assert data == testdata


async def test_write(testdatafile: PosixPath, testdata: bytes) -> None:
    async with await open_file(testdatafile, 'ab') as f:
        await f.write(b'f' * 1000)

    assert testdatafile.stat().st_size == len(testdata) + 1000


async def test_async_iteration(tmp_path: PosixPath) -> None:
    lines = ['blah blah\n', 'foo foo\n', 'bar bar']
    testpath = tmp_path.joinpath('testfile')
    testpath.write_text(''.join(lines), 'ascii')
    async with await open_file(str(testpath)) as f:
        lines_i = iter(lines)
        async for line in f:
            assert line == next(lines_i)  # type: ignore[comparison-overlap]
