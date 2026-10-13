from __future__ import annotations

import errno
from io import BufferedWriter, RawIOBase
from pathlib import Path
from typing import TYPE_CHECKING

import pytest
from _pytest.fixtures import SubRequest
from _pytest.tmpdir import TempPathFactory

from anyio import (
    BrokenResourceError,
    CancelScope,
    ClosedResourceError,
    EndOfStream,
    from_thread,
    get_cancelled_exc_class,
)
from anyio.streams.file import FileReadStream, FileStreamAttribute, FileWriteStream

if TYPE_CHECKING:
    from anyio.abc import ByteReceiveStream


class TestFileReadStream:
    @pytest.fixture(scope="class")
    @classmethod
    def file_path(cls, tmp_path_factory: TempPathFactory) -> Path:
        path = tmp_path_factory.mktemp("filestream") / "data.txt"
        path.write_text("Hello")
        return path

    @pytest.fixture(params=[False, True], ids=["str", "path"])
    def file_path_or_str(self, request: SubRequest, file_path: Path) -> Path | str:
        return file_path if request.param else str(file_path)

    async def _run_filestream_test(self, stream: ByteReceiveStream) -> None:
        assert await stream.receive(3) == b"Hel"
        assert await stream.receive(3) == b"lo"
        with pytest.raises(EndOfStream):
            await stream.receive(1)

    async def test_read_file_as_path(self, file_path_or_str: Path | str) -> None:
        async with await FileReadStream.from_path(file_path_or_str) as stream:
            await self._run_filestream_test(stream)

    async def test_read_file(self, file_path: Path) -> None:
        with file_path.open("rb") as file:
            async with FileReadStream(file) as stream:
                await self._run_filestream_test(stream)

    async def test_read_after_close(self, file_path: Path) -> None:
        async with await FileReadStream.from_path(file_path) as stream:
            pass

        with pytest.raises(ClosedResourceError):
            await stream.receive()

    async def test_close_on_cancel(self, file_path: Path) -> None:
        stream = await FileReadStream.from_path(file_path)
        file = stream.extra(FileStreamAttribute.file)
        try:
            with CancelScope() as scope:
                with pytest.raises(get_cancelled_exc_class()):
                    async with stream:
                        scope.cancel()

            assert file.closed
        finally:
            file.close()

    @pytest.mark.parametrize("max_bytes", [0, -1])
    async def test_receive_invalid_max_bytes(
        self, file_path: Path, max_bytes: int
    ) -> None:
        async with await FileReadStream.from_path(file_path) as stream:
            with pytest.raises(
                ValueError, match="max_bytes must be a positive integer"
            ):
                await stream.receive(max_bytes)

    async def test_seek(self, file_path: Path) -> None:
        with file_path.open("rb") as file:
            async with FileReadStream(file) as stream:
                await stream.seek(2)
                assert await stream.tell() == 2
                data = await stream.receive()
                assert data == b"llo"
                assert await stream.tell() == 5

    async def test_extra_attributes(self, file_path: Path) -> None:
        async with await FileReadStream.from_path(file_path) as stream:
            path = stream.extra(FileStreamAttribute.path)
            assert path == file_path

            fileno = stream.extra(FileStreamAttribute.fileno)
            assert fileno > 2

            file = stream.extra(FileStreamAttribute.file)
            assert file.fileno() == fileno


class TestFileWriteStream:
    @pytest.fixture
    def file_path(self, tmp_path: Path) -> Path:
        return tmp_path / "written_data.txt"

    async def test_write_file(self, file_path: Path) -> None:
        async with await FileWriteStream.from_path(file_path) as stream:
            await stream.send(b"Hel")
            await stream.send(b"lo")

        assert file_path.read_text() == "Hello"

    async def test_short_writes(
        self, file_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = b"complete payload including a tail"

        async def exercise(path: Path, buffered: bool) -> None:
            with path.open("wb", buffering=0) as file:
                assert isinstance(file, RawIOBase)
                original_write = file.write
                calls = 0

                def short_write(data: bytes | memoryview) -> int | None:
                    nonlocal calls
                    calls += 1
                    return original_write(data[:3])

                monkeypatch.setattr(file, "write", short_write)
                if buffered:
                    with BufferedWriter(file, buffer_size=4) as writer:
                        writer.write(payload)
                else:
                    async with FileWriteStream(file) as stream:
                        await stream.send(payload)

            assert path.read_bytes() == payload
            assert calls > 1

        await exercise(file_path.with_suffix(".control"), True)
        await exercise(file_path, False)

    async def test_send_preserves_bytes_input(
        self, file_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        payload = b"complete payload including a tail"
        with file_path.open("wb", buffering=0) as file:
            original_write = file.write

            def write(data: bytes) -> int:
                assert isinstance(data, bytes)
                return original_write(data[:3])

            monkeypatch.setattr(file, "write", write)
            async with FileWriteStream(file) as stream:
                await stream.send(payload)

        assert file_path.read_bytes() == payload

    @pytest.mark.parametrize("no_progress", [0, None])
    async def test_short_write_then_no_progress(
        self,
        file_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        no_progress: int | None,
    ) -> None:
        with file_path.open("wb", buffering=0) as file:
            original_write = file.write
            calls = 0

            def write(data: bytes | memoryview) -> int | None:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return original_write(data[:3])

                return no_progress

            monkeypatch.setattr(file, "write", write)
            async with FileWriteStream(file) as stream:
                with pytest.raises(BrokenResourceError):
                    await stream.send(b"complete payload")

            assert calls == 2

        assert file_path.read_bytes() == b"com"

    async def test_short_write_then_oserror(
        self, file_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        error = OSError(errno.ENOSPC, "No space left on device")
        with file_path.open("wb", buffering=0) as file:
            original_write = file.write
            calls = 0

            def write(data: bytes | memoryview) -> int:
                nonlocal calls
                calls += 1
                if calls == 1:
                    return original_write(data[:3])

                raise error

            monkeypatch.setattr(file, "write", write)
            async with FileWriteStream(file) as stream:
                with pytest.raises(BrokenResourceError) as exc:
                    await stream.send(b"complete payload")

            assert exc.value.__cause__ is error

        assert file_path.read_bytes() == b"com"

    async def test_empty_write(
        self, file_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with file_path.open("wb", buffering=0) as file:
            original_write = file.write
            calls = []

            def write(data: bytes | memoryview) -> int:
                calls.append(bytes(data))
                return original_write(data)

            monkeypatch.setattr(file, "write", write)
            async with FileWriteStream(file) as stream:
                await stream.send(b"")

        assert calls == [b""]
        assert file_path.read_bytes() == b""

    @pytest.mark.parametrize("item", [b"foo", b""])
    async def test_send_pending_cancellation(
        self, file_path: Path, item: bytes
    ) -> None:
        async with await FileWriteStream.from_path(file_path) as stream:
            with CancelScope() as scope:
                scope.cancel()
                with pytest.raises(get_cancelled_exc_class()):
                    await stream.send(item)

        assert file_path.read_bytes() == b""

    async def test_cancellation_after_short_write(
        self, file_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        with file_path.open("wb", buffering=0) as file:
            original_write = file.write

            def write(data: bytes | memoryview) -> int:
                written = original_write(data[:3])
                from_thread.run_sync(scope.cancel)
                return written

            monkeypatch.setattr(file, "write", write)
            async with FileWriteStream(file) as stream:
                with CancelScope() as scope:
                    with pytest.raises(get_cancelled_exc_class()):
                        await stream.send(b"complete payload")

        assert file_path.read_bytes() == b"com"

    async def test_append_file(self, file_path: Path) -> None:
        file_path.write_text("Hello")
        async with await FileWriteStream.from_path(file_path, True) as stream:
            await stream.send(b", World!")

        assert file_path.read_text() == "Hello, World!"

    @pytest.mark.parametrize("item", [b"foo", b""])
    async def test_write_after_close(self, file_path: Path, item: bytes) -> None:
        async with await FileWriteStream.from_path(file_path, True) as stream:
            pass

        with pytest.raises(ClosedResourceError):
            await stream.send(item)

    async def test_close_on_cancel(self, file_path: Path) -> None:
        stream = await FileWriteStream.from_path(file_path)
        file = stream.extra(FileStreamAttribute.file)
        try:
            with CancelScope() as scope:
                with pytest.raises(get_cancelled_exc_class()):
                    async with stream:
                        scope.cancel()

            assert file.closed
        finally:
            file.close()

    async def test_extra_attributes(self, file_path: Path) -> None:
        async with await FileWriteStream.from_path(file_path) as stream:
            path = stream.extra(FileStreamAttribute.path)
            assert path == file_path

            fileno = stream.extra(FileStreamAttribute.fileno)
            assert fileno > 2

            file = stream.extra(FileStreamAttribute.file)
            assert file.fileno() == fileno
