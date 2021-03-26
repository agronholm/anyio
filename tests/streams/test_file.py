import pytest

from anyio import ClosedResourceError, EndOfStream
from anyio.streams.file import FileReadStream, FileStreamAttribute, FileWriteStream

pytestmark = pytest.mark.anyio


class TestFileReadStream:
    @pytest.fixture(scope='class')
    def file_path(self, tmp_path_factory):
        path = tmp_path_factory.mktemp('filestream') / 'data.txt'
        path.write_text('Hello')
        return path

    async def _run_filestream_test(self, stream):
        assert await stream.receive(3) == b'Hel'
        assert await stream.receive(3) == b'lo'
        with pytest.raises(EndOfStream):
            await stream.receive(1)

    @pytest.mark.parametrize('as_path', [True, False], ids=['path', 'str'])
    async def test_read_file_as_path(self, file_path, as_path):
        if not as_path:
            file_path = str(file_path)

        async with await FileReadStream.from_path(file_path) as stream:
            await self._run_filestream_test(stream)

    async def test_read_file(self, file_path):
        with file_path.open('rb') as file:
            async with FileReadStream(file) as stream:
                await self._run_filestream_test(stream)

    async def test_read_after_close(self, file_path):
        async with await FileReadStream.from_path(file_path) as stream:
            pass

        with pytest.raises(ClosedResourceError):
            await stream.receive()

    async def test_seek(self, file_path):
        with file_path.open('rb') as file:
            async with FileReadStream(file) as stream:
                await stream.seek(2)
                assert await stream.tell() == 2
                data = await stream.receive()
                assert data == b'llo'
                assert await stream.tell() == 5

    async def test_extra_attributes(self, file_path):
        async with await FileReadStream.from_path(file_path) as stream:
            path = stream.extra(FileStreamAttribute.path)
            assert path == file_path

            fileno = stream.extra(FileStreamAttribute.fileno)
            assert fileno > 2

            file = stream.extra(FileStreamAttribute.file)
            assert file.fileno() == fileno


class TestFileWriteStream:
    @pytest.fixture
    def file_path(self, tmp_path):
        return tmp_path / 'written_data.txt'

    async def test_write_file(self, file_path):
        async with await FileWriteStream.from_path(file_path) as stream:
            await stream.send(b'Hel')
            await stream.send(b'lo')

        assert file_path.read_text() == 'Hello'

    async def test_append_file(self, file_path):
        file_path.write_text('Hello')
        async with await FileWriteStream.from_path(file_path, True) as stream:
            await stream.send(b', World!')

        assert file_path.read_text() == 'Hello, World!'

    async def test_write_after_close(self, file_path):
        async with await FileWriteStream.from_path(file_path, True) as stream:
            pass

        with pytest.raises(ClosedResourceError):
            await stream.send(b'foo')

    async def test_extra_attributes(self, file_path):
        async with await FileWriteStream.from_path(file_path) as stream:
            path = stream.extra(FileStreamAttribute.path)
            assert path == file_path

            fileno = stream.extra(FileStreamAttribute.fileno)
            assert fileno > 2

            file = stream.extra(FileStreamAttribute.file)
            assert file.fileno() == fileno
