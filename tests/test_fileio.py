from pathlib import Path

import pytest

from anyio import aopen


@pytest.fixture(scope='module')
def testdata():
    return b''.join(bytes([i] * 1000) for i in range(10))


@pytest.fixture
def testdatafile(tmpdir_factory, testdata):
    file = tmpdir_factory.mktemp('file').join('testdata')
    file.write(testdata)
    return Path(str(file))


@pytest.mark.anyio
async def test_read(testdatafile, testdata):
    async with await aopen(testdatafile, 'rb') as f:
        data = await f.read()

    assert f.closed
    assert data == testdata


@pytest.mark.anyio
async def test_write(testdatafile, testdata):
    async with await aopen(testdatafile, 'ab') as f:
        await f.write(b'f' * 1000)

    assert testdatafile.stat().st_size == len(testdata) + 1000


@pytest.mark.anyio
async def test_async_iteration(tmpdir):
    lines = ['blah blah\n', 'foo foo\n', 'bar bar']
    testpath = tmpdir.join('testfile')
    testpath.write_text(''.join(lines), 'ascii')
    async with await aopen(str(testpath)) as f:
        lines_i = iter(lines)
        async for line in f:
            assert line == next(lines_i)
