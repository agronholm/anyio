from __future__ import annotations

import sys
import tempfile
from functools import partial
from types import TracebackType
from typing import Any, AnyStr, Callable, Generic, cast

from .. import to_thread
from .._core._fileio import AsyncFile


class TemporaryFile(Generic[AnyStr]):
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

    async def __aenter__(self) -> AsyncFile:
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

    async def __aenter__(self) -> SpooledTemporaryFile:
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
        self._async_file = AsyncFile(fp)
        return self

    async def rollover(self) -> None:
        if self._async_file is None:
            raise RuntimeError("Internal file is not initialized.")
        await to_thread.run_sync(cast(Callable[[], None], self._async_file.rollover))

    @property
    def closed(self) -> bool:
        if self._async_file is not None:
            try:
                return bool(self._async_file.closed)
            except AttributeError:
                f = getattr(self._async_file, "_f", None)
                if f is None:
                    return True
                return bool(f.closed)
        return True

    def __getattr__(self, attr: str) -> Any:
        if self._async_file is not None:
            return getattr(self._async_file, attr)
        raise AttributeError(f"{self.__class__.__name__} has no attribute {attr}")

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


async def mkstemp(
    suffix: AnyStr | None = None,
    prefix: AnyStr | None = None,
    dir: AnyStr | None = None,
    text: bool = False,
) -> tuple[int, str | bytes]:
    return await to_thread.run_sync(lambda: tempfile.mkstemp(suffix, prefix, dir, text))


async def mkdtemp(
    suffix: AnyStr | None = None,
    prefix: AnyStr | None = None,
    dir: AnyStr | None = None,
) -> str | bytes:
    return await to_thread.run_sync(lambda: tempfile.mkdtemp(suffix, prefix, dir))


async def gettempdir() -> str:
    return await to_thread.run_sync(tempfile.gettempdir)


async def gettempdirb() -> bytes:
    return await to_thread.run_sync(tempfile.gettempdirb)
