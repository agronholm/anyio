from __future__ import annotations

import sys
import tempfile
from functools import partial
from types import TracebackType
from typing import Any, AnyStr, Callable, Generic, cast, overload

from .. import to_thread
from .._core._fileio import AsyncFile


class TemporaryFile(Generic[AnyStr]):
    """
    An asynchronous temporary file that is automatically created and cleaned up.

    This class provides an asynchronous context manager interface to a temporary file.
    The file is created using Python's standard `tempfile.TemporaryFile` function in a
    background thread, and is wrapped as an asynchronous file using `AsyncFile`.

    :param mode: The mode in which the file is opened. Defaults to "w+b".
    :param buffering: The buffering policy (-1 means the default buffering).
    :param encoding: The encoding used to decode or encode the file. Only applicable in text mode.
    :param newline: Controls how universal newlines mode works (only applicable in text mode).
    :param suffix: The suffix for the temporary file name.
    :param prefix: The prefix for the temporary file name.
    :param dir: The directory in which the temporary file is created.
    :param errors: The error handling scheme used for encoding/decoding errors.
    """

    def __init__(
        self,
        mode: str = "w+b",
        buffering: int = -1,
        encoding: str | None = None,
        newline: str | None = None,
        suffix: AnyStr | None = None,
        prefix: AnyStr | None = None,
        dir: AnyStr | None = None,
        *,
        errors: str | None = None,
    ) -> None:
        self.mode = mode
        self.buffering = buffering
        self.encoding = encoding
        self.newline = newline
        self.suffix: AnyStr | None = suffix
        self.prefix: AnyStr | None = prefix
        self.dir: AnyStr | None = dir
        self.errors = errors

        self._async_file: AsyncFile | None = None

    async def __aenter__(self) -> AsyncFile[AnyStr]:
        fp = await to_thread.run_sync(
            lambda: tempfile.TemporaryFile(
                self.mode,
                self.buffering,
                self.encoding,
                self.newline,
                self.suffix,
                self.prefix,
                self.dir,
                errors=self.errors,
            )
        )
        self._async_file = AsyncFile(fp)
        return self._async_file

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._async_file is not None:
            await self._async_file.aclose()
            self._async_file = None


class NamedTemporaryFile(Generic[AnyStr]):
    """
    An asynchronous named temporary file that is automatically created and cleaned up.

    This class provides an asynchronous context manager for a temporary file with a
    visible name in the file system. It uses Python's standard `tempfile.NamedTemporaryFile`
    function and wraps the file object with `AsyncFile` for asynchronous operations.

    :param mode: The mode in which the file is opened. Defaults to "w+b".
    :param buffering: The buffering policy (-1 means the default buffering).
    :param encoding: The encoding used to decode or encode the file. Only applicable in text mode.
    :param newline: Controls how universal newlines mode works (only applicable in text mode).
    :param suffix: The suffix for the temporary file name.
    :param prefix: The prefix for the temporary file name.
    :param dir: The directory in which the temporary file is created.
    :param delete: Whether to delete the file when it is closed.
    :param errors: The error handling scheme used for encoding/decoding errors.
    :param delete_on_close: (Python 3.12+) Whether to delete the file on close.
    """

    def __init__(
        self,
        mode: str = "w+b",
        buffering: int = -1,
        encoding: str | None = None,
        newline: str | None = None,
        suffix: AnyStr | None = None,
        prefix: AnyStr | None = None,
        dir: AnyStr | None = None,
        delete: bool = True,
        *,
        errors: str | None = None,
        delete_on_close: bool = True,
    ) -> None:
        self.mode = mode
        self.buffering = buffering
        self.encoding = encoding
        self.newline = newline
        self.suffix: AnyStr | None = suffix
        self.prefix: AnyStr | None = prefix
        self.dir: AnyStr | None = dir
        self.delete = delete
        self.errors = errors
        self.delete_on_close = delete_on_close

        self._async_file: AsyncFile | None = None

    async def __aenter__(self) -> AsyncFile[AnyStr]:
        params: dict[str, Any] = {
            "mode": self.mode,
            "buffering": self.buffering,
            "encoding": self.encoding,
            "newline": self.newline,
            "suffix": self.suffix,
            "prefix": self.prefix,
            "dir": self.dir,
            "delete": self.delete,
            "errors": self.errors,
        }
        if sys.version_info >= (3, 12):
            params["delete_on_close"] = self.delete_on_close

        fp = await to_thread.run_sync(lambda: tempfile.NamedTemporaryFile(**params))
        self._async_file = AsyncFile(fp)
        return self._async_file

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._async_file is not None:
            await self._async_file.aclose()
            self._async_file = None


class SpooledTemporaryFile(Generic[AnyStr]):
    """
    An asynchronous spooled temporary file that starts in memory and is spooled to disk.

    This class provides an asynchronous interface to a spooled temporary file using
    Python's standard `tempfile.SpooledTemporaryFile`. It supports asynchronous write
    operations and provides a method to force a rollover to disk.

    :param max_size: Maximum size in bytes before the file is rolled over to disk.
    :param mode: The mode in which the file is opened. Defaults to "w+b".
    :param buffering: The buffering policy (-1 means the default buffering).
    :param encoding: The encoding used to decode or encode the file (text mode only).
    :param newline: Controls how universal newlines mode works (text mode only).
    :param suffix: The suffix for the temporary file name.
    :param prefix: The prefix for the temporary file name.
    :param dir: The directory in which the temporary file is created.
    :param errors: The error handling scheme used for encoding/decoding errors.
    """

    def __init__(
        self,
        max_size: int = 0,
        mode: str = "w+b",
        buffering: int = -1,
        encoding: str | None = None,
        newline: str | None = None,
        suffix: AnyStr | None = None,
        prefix: AnyStr | None = None,
        dir: AnyStr | None = None,
        *,
        errors: str | None = None,
    ) -> None:
        self.max_size = max_size
        self.mode = mode
        self.buffering = buffering
        self.encoding = encoding
        self.newline = newline
        self.suffix: AnyStr | None = suffix
        self.prefix: AnyStr | None = prefix
        self.dir: AnyStr | None = dir
        self.errors = errors
        self._async_file: AsyncFile | None = None
        self._fp: Any = None

    async def __aenter__(
        self: SpooledTemporaryFile[AnyStr],
    ) -> SpooledTemporaryFile[AnyStr]:
        fp = await to_thread.run_sync(
            partial(
                tempfile.SpooledTemporaryFile,
                self.max_size,
                self.mode,
                self.buffering,
                self.encoding,
                self.newline,
                self.suffix,
                self.prefix,
                self.dir,
                errors=self.errors,
            )
        )
        self._fp = fp
        self._async_file = AsyncFile(fp)
        return self

    async def rollover(self) -> None:
        if self._fp is None:
            raise RuntimeError("Underlying file is not initialized.")

        await to_thread.run_sync(cast(Callable[[], None], self._fp.rollover))

    @property
    def closed(self) -> bool:
        if self._fp is None:
            return True

        return bool(self._fp.closed)

    def __getattr__(self, attr: str) -> Any:
        if self._async_file is not None:
            return getattr(self._async_file, attr)

        raise AttributeError(f"{self.__class__.__name__} has no attribute {attr}")

    async def write(self, s: Any) -> int:
        """
        Asynchronously write data to the spooled temporary file.

        If the file has not yet been rolled over, the data is written synchronously,
        and a rollover is triggered if the size exceeds the maximum size.

        :param s: The data to write.
        :return: The number of bytes written.
        :raises RuntimeError: If the underlying file is not initialized.
        """
        if self._fp is None:
            raise RuntimeError("Underlying file is not initialized.")

        if not getattr(self._fp, "_rolled", True):
            result = self._fp.write(s)
            if self._fp._max_size and self._fp.tell() > self._fp._max_size:
                self._fp.rollover()

            return result

        return await to_thread.run_sync(self._fp.write, s)

    async def writelines(self, lines: Any) -> None:
        """
        Asynchronously write a list of lines to the spooled temporary file.

        If the file has not yet been rolled over, the lines are written synchronously,
        and a rollover is triggered if the size exceeds the maximum size.

        :param lines: An iterable of lines to write.
        :raises RuntimeError: If the underlying file is not initialized.
        """
        if self._fp is None:
            raise RuntimeError("Underlying file is not initialized.")

        if not getattr(self._fp, "_rolled", True):
            result = self._fp.writelines(lines)
            if self._fp._max_size and self._fp.tell() > self._fp._max_size:
                self._fp.rollover()

            return result

        return await to_thread.run_sync(self._fp.writelines, lines)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._async_file is not None:
            await self._async_file.aclose()
            self._async_file = None


class TemporaryDirectory(Generic[AnyStr]):
    """
    An asynchronous temporary directory that is created and cleaned up automatically.

    This class provides an asynchronous context manager for creating a temporary directory.
    It wraps Python's standard `tempfile.TemporaryDirectory` to perform directory creation
    and cleanup operations in a background thread.

    :param suffix: Suffix to be added to the temporary directory name.
    :param prefix: Prefix to be added to the temporary directory name.
    :param dir: The parent directory where the temporary directory is created.
    :param ignore_cleanup_errors: Whether to ignore errors during cleanup (Python 3.10+).
    :param delete: Whether to delete the directory upon closing (Python 3.12+).
    """

    def __init__(
        self,
        suffix: AnyStr | None = None,
        prefix: AnyStr | None = None,
        dir: AnyStr | None = None,
        *,
        ignore_cleanup_errors: bool = False,
        delete: bool = True,
    ) -> None:
        self.suffix: AnyStr | None = suffix
        self.prefix: AnyStr | None = prefix
        self.dir: AnyStr | None = dir
        self.ignore_cleanup_errors = ignore_cleanup_errors
        self.delete = delete

        self._tempdir: tempfile.TemporaryDirectory | None = None

    async def __aenter__(self) -> str:
        params: dict[str, Any] = {
            "suffix": self.suffix,
            "prefix": self.prefix,
            "dir": self.dir,
        }
        if sys.version_info >= (3, 10):
            params["ignore_cleanup_errors"] = self.ignore_cleanup_errors

        if sys.version_info >= (3, 12):
            params["delete"] = self.delete

        self._tempdir = await to_thread.run_sync(
            lambda: tempfile.TemporaryDirectory(**params)
        )
        return await to_thread.run_sync(self._tempdir.__enter__)

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_value: BaseException | None,
        traceback: TracebackType | None,
    ) -> None:
        if self._tempdir is not None:
            await to_thread.run_sync(
                self._tempdir.__exit__, exc_type, exc_value, traceback
            )

    async def cleanup(self) -> None:
        if self._tempdir is not None:
            await to_thread.run_sync(self._tempdir.cleanup)


@overload
async def mkstemp(
    suffix: str | None = None,
    prefix: str | None = None,
    dir: str | None = None,
    text: bool = False,
) -> tuple[int, str]: ...


@overload
async def mkstemp(
    suffix: bytes | None = None,
    prefix: bytes | None = None,
    dir: bytes | None = None,
    text: bool = False,
) -> tuple[int, bytes]: ...


async def mkstemp(
    suffix: AnyStr | None = None,
    prefix: AnyStr | None = None,
    dir: AnyStr | None = None,
    text: bool = False,
) -> tuple[int, str | bytes]:
    """
    Asynchronously create a temporary file and return an OS-level handle and the file name.

    This function wraps `tempfile.mkstemp` and executes it in a background thread.

    :param suffix: Suffix to be added to the file name.
    :param prefix: Prefix to be added to the file name.
    :param dir: Directory in which the temporary file is created.
    :param text: Whether the file is opened in text mode.
    :return: A tuple containing the file descriptor and the file name.
    """
    return await to_thread.run_sync(tempfile.mkstemp, suffix, prefix, dir, text)


@overload
async def mkdtemp(
    suffix: str | None = None,
    prefix: str | None = None,
    dir: str | None = None,
) -> str: ...


@overload
async def mkdtemp(
    suffix: bytes | None = None,
    prefix: bytes | None = None,
    dir: bytes | None = None,
) -> bytes: ...


async def mkdtemp(
    suffix: AnyStr | None = None,
    prefix: AnyStr | None = None,
    dir: AnyStr | None = None,
) -> str | bytes:
    """
    Asynchronously create a temporary directory and return its path.

    This function wraps `tempfile.mkdtemp` and executes it in a background thread.

    :param suffix: Suffix to be added to the directory name.
    :param prefix: Prefix to be added to the directory name.
    :param dir: Parent directory where the temporary directory is created.
    :return: The path of the created temporary directory.
    """
    return await to_thread.run_sync(tempfile.mkdtemp, suffix, prefix, dir)


async def gettempdir() -> str:
    """
    Asynchronously return the name of the directory used for temporary files.

    This function wraps `tempfile.gettempdir` and executes it in a background thread.

    :return: The path of the temporary directory as a string.
    """
    return await to_thread.run_sync(tempfile.gettempdir)


async def gettempdirb() -> bytes:
    """
    Asynchronously return the name of the directory used for temporary files in bytes.

    This function wraps `tempfile.gettempdirb` and executes it in a background thread.

    :return: The path of the temporary directory as bytes.
    """
    return await to_thread.run_sync(tempfile.gettempdirb)
