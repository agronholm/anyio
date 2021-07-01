import pathlib
import platform
from typing import Tuple

import pytest
from _pytest.tmpdir import TempPathFactory

from anyio import Path, open_file

pytestmark = pytest.mark.anyio


class TestAsyncFile:
    @pytest.fixture(scope='class')
    def testdata(cls) -> bytes:
        return b''.join(bytes([i] * 1000) for i in range(10))

    @pytest.fixture
    def testdatafile(self, tmp_path_factory: TempPathFactory, testdata: bytes) -> pathlib.Path:
        file = tmp_path_factory.mktemp('file').joinpath('testdata')
        file.write_bytes(testdata)
        return file

    async def test_open_close(self, testdatafile: pathlib.Path) -> None:
        f = await open_file(testdatafile)
        await f.aclose()

    async def test_read(self, testdatafile: pathlib.Path, testdata: bytes) -> None:
        async with await open_file(testdatafile, 'rb') as f:
            data = await f.read()

        assert f.closed
        assert data == testdata

    async def test_write(self, testdatafile: pathlib.Path, testdata: bytes) -> None:
        async with await open_file(testdatafile, 'ab') as f:
            await f.write(b'f' * 1000)

        assert testdatafile.stat().st_size == len(testdata) + 1000

    async def test_async_iteration(self, tmp_path: pathlib.Path) -> None:
        lines = ['blah blah\n', 'foo foo\n', 'bar bar']
        testpath = tmp_path.joinpath('testfile')
        testpath.write_text(''.join(lines), 'ascii')
        async with await open_file(str(testpath)) as f:
            lines_i = iter(lines)
            async for line in f:
                assert line == next(lines_i)  # type: ignore[comparison-overlap]


class TestPath:
    @pytest.fixture
    def populated_tmpdir(self, tmp_path: pathlib.Path) -> pathlib.Path:
        tmp_path.joinpath('testfile').touch()
        tmp_path.joinpath('testfile2').touch()
        subdir = tmp_path / 'subdir'
        subdir.mkdir()
        subdir.joinpath('dummyfile1.txt').touch()
        subdir.joinpath('dummyfile2.txt').touch()
        return tmp_path

    async def test_properties(self) -> None:
        """Ensure that all public properties and methods are available on the async Path class."""
        path = pathlib.Path('/test/path/another/part')
        stdlib_properties = {p for p in dir(path) if p.startswith('__') or not p.startswith('_')}
        stdlib_properties.discard('link_to')
        stdlib_properties.discard('__class_getitem__')

        async_path = Path(path)
        anyio_properties = {p for p in dir(async_path)
                            if p.startswith('__') or not p.startswith('_')}

        missing = stdlib_properties - anyio_properties
        assert not missing

    def test_name_property(self) -> None:
        assert Path('/abc/xyz/foo.txt.zip').name == 'foo.txt.zip'

    def test_parent_property(self) -> None:
        parent = Path('/abc/xyz/foo.txt').parent
        assert isinstance(parent, Path)
        assert str(parent) == '/abc/xyz'

    def test_parents_property(self) -> None:
        parents = Path('/abc/xyz/foo.txt').parents
        assert len(parents) == 3
        assert all(isinstance(parent, Path) for parent in parents)
        assert str(parents[0]) == '/abc/xyz'
        assert str(parents[1]) == '/abc'
        assert str(parents[2]) == '/'

    def test_stem_property(self) -> None:
        assert Path('/abc/xyz/foo.txt.zip').stem == 'foo.txt'

    def test_suffix_property(self) -> None:
        assert Path('/abc/xyz/foo.txt.zip').suffix == '.zip'

    def test_suffixes_property(self) -> None:
        assert Path('/abc/xyz/foo.tar.gz').suffixes == ['.tar', '.gz']

    @pytest.mark.parametrize('args, result', [
        (('/xyz', 'abc'), True),
        (('/xyz', 'baz'), False)
    ])
    def test_is_relative_to(self, args: Tuple[str], result: bool) -> None:
        assert Path('/xyz/abc/foo').is_relative_to(*args) == result

    async def test_glob(self, populated_tmpdir: pathlib.Path) -> None:
        all_paths = []
        async for path in Path(populated_tmpdir).glob('**/*.txt'):
            assert isinstance(path, Path)
            all_paths.append(path.name)

        all_paths.sort()
        assert all_paths == ['dummyfile1.txt', 'dummyfile2.txt']

    async def test_rglob(self, populated_tmpdir: pathlib.Path) -> None:
        all_paths = []
        async for path in Path(populated_tmpdir).rglob('*.txt'):
            assert isinstance(path, Path)
            all_paths.append(path.name)

        all_paths.sort()
        assert all_paths == ['dummyfile1.txt', 'dummyfile2.txt']

    async def test_iterdir(self, populated_tmpdir: pathlib.Path) -> None:
        all_paths = []
        async for path in Path(populated_tmpdir).iterdir():
            assert isinstance(path, Path)
            all_paths.append(path.name)

        all_paths.sort()
        assert all_paths == ['subdir', 'testfile', 'testfile2']

    @pytest.mark.skipif(platform.platform() == 'Windows',
                        reason='chmod() is not available on Windows')
    async def test_chmod(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.touch(0o666)
        await Path(path).chmod(0o444)
        assert path.stat().st_mode & 0o777 == 0o444

    @pytest.mark.skipif(platform.platform() == 'Windows',
                        reason='symbolic links are not supported on Windows')
    async def test_readlink(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path.joinpath('testfile')
        path.symlink_to('/foo/bar/baz')
        link_target = await Path(path).readlink()
        assert isinstance(link_target, Path)
        assert str(link_target) == '/foo/bar/baz'

    async def test_read_bytes(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.write_bytes(b'bibbitibobbitiboo')
        assert await Path(path).read_bytes() == b'bibbitibobbitiboo'

    async def test_read_text(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.write_text('some text åäö', encoding='utf-8')
        assert await Path(path).read_text(encoding='utf-8') == 'some text åäö'

    async def test_touch(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).touch()
        assert path.is_file()

    async def test_unlink(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        path.touch()
        await Path(path).unlink()
        assert not path.exists()

    def test_with_name(self) -> None:
        assert Path('/xyz/foo.txt').with_name('bar').name == 'bar'

    def test_with_stem(self) -> None:
        assert Path('/xyz/foo.txt').with_stem('bar').name == 'bar.txt'

    def test_with_suffix(self) -> None:
        assert Path('/xyz/foo.txt.gz').with_suffix('.zip').name == 'foo.txt.zip'

    async def test_write_bytes(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).write_bytes(b'bibbitibobbitiboo')
        assert path.read_bytes() == b'bibbitibobbitiboo'

    async def test_write_text(self, tmp_path: pathlib.Path) -> None:
        path = tmp_path / 'testfile'
        await Path(path).write_text('some text åäö', encoding='utf-8')
        assert path.read_text(encoding='utf-8') == 'some text åäö'
