import os
import pathlib
import sys
from dataclasses import dataclass
from functools import partial
from os import PathLike
from typing import Any, AsyncIterator, Callable, Generic, Iterator, Optional, TypeVar, Union

from .. import to_thread
from ..abc import AsyncResource
from ._synchronization import CapacityLimiter

if sys.version_info >= (3, 8):
    from typing import Final
else:
    from typing_extensions import Final

T_Fp = TypeVar("T_Fp")


class AsyncFile(AsyncResource, Generic[T_Fp]):
    """
    An asynchronous file object.

    This class wraps a standard file object and provides async friendly versions of the following
    blocking methods (where available on the original file object):

    * read
    * read1
    * readline
    * readlines
    * readinto
    * readinto1
    * write
    * writelines
    * truncate
    * seek
    * tell
    * flush

    All other methods are directly passed through.

    This class supports the asynchronous context manager protocol which closes the underlying file
    at the end of the context block.

    This class also supports asynchronous iteration::

        async with await open_file(...) as f:
            async for line in f:
                print(line)
    """

    def __init__(self, fp: T_Fp) -> None:
        self._fp: Any = fp

    def __getattr__(self, name: str) -> object:
        return getattr(self._fp, name)

    @property
    def wrapped(self) -> T_Fp:
        """The wrapped file object."""
        return self._fp

    async def __aiter__(self) -> AsyncIterator[bytes]:
        while True:
            line = await self.readline()
            if line:
                yield line
            else:
                break

    async def aclose(self) -> None:
        return await to_thread.run_sync(self._fp.close)

    async def read(self, size: int = -1) -> Union[bytes, str]:
        return await to_thread.run_sync(self._fp.read, size)

    async def read1(self, size: int = -1) -> Union[bytes, str]:
        return await to_thread.run_sync(self._fp.read1, size)

    async def readline(self) -> bytes:
        return await to_thread.run_sync(self._fp.readline)

    async def readlines(self) -> bytes:
        return await to_thread.run_sync(self._fp.readlines)

    async def readinto(self, b: Union[bytes, memoryview]) -> bytes:
        return await to_thread.run_sync(self._fp.readinto, b)

    async def readinto1(self, b: Union[bytes, memoryview]) -> bytes:
        return await to_thread.run_sync(self._fp.readinto1, b)

    async def write(self, b: bytes) -> None:
        return await to_thread.run_sync(self._fp.write, b)

    async def writelines(self, lines: bytes) -> None:
        return await to_thread.run_sync(self._fp.writelines, lines)

    async def truncate(self, size: Optional[int] = None) -> int:
        return await to_thread.run_sync(self._fp.truncate, size)

    async def seek(self, offset: int, whence: Optional[int] = os.SEEK_SET) -> int:
        return await to_thread.run_sync(self._fp.seek, offset, whence)

    async def tell(self) -> int:
        return await to_thread.run_sync(self._fp.tell)

    async def flush(self) -> None:
        return await to_thread.run_sync(self._fp.flush)


async def open_file(file: Union[str, PathLike, int], mode: str = 'r', buffering: int = -1,
                    encoding: Optional[str] = None, errors: Optional[str] = None,
                    newline: Optional[str] = None, closefd: bool = True,
                    opener: Optional[Callable] = None) -> AsyncFile:
    """
    Open a file asynchronously.

    The arguments are exactly the same as for the builtin :func:`open`.

    :return: an asynchronous file object

    """
    fp = await to_thread.run_sync(open, file, mode, buffering, encoding, errors, newline,
                                  closefd, opener)
    return AsyncFile(fp)


@dataclass(eq=False)
class _PathIterator(AsyncIterator['Path']):
    iterator: Iterator[pathlib.Path]
    limiter: Optional[CapacityLimiter] = None

    async def __anext__(self) -> 'Path':
        nextval = await to_thread.run_sync(next, self.iterator, None, cancellable=True,
                                           limiter=self.limiter)
        if nextval is None:
            raise StopAsyncIteration from None

        return nextval


class Path(PathLike):
    def __init__(self, *args: Union[str, pathlib.Path]) -> None:
        self._path: Final[pathlib.Path] = pathlib.Path(*args)

    def __getattr__(self, item: str) -> Any:
        return getattr(self._path, item)

    def __fspath__(self) -> str:
        return self._path.__fspath__()

    def __truediv__(self, other: object) -> 'Path':
        if isinstance(other, Path):
            other = other._path

        if isinstance(other, (str, pathlib.PurePath)):
            return Path(self._path / other)

        return NotImplemented

    def absolute(self) -> 'Path':
        return Path(self._path.absolute())

    def as_posix(self) -> 'Path':
        return Path(self._path.as_posix())

    def as_uri(self) -> 'Path':
        return Path(self._path.as_uri())

    async def chmod(self, mode: int) -> None:
        return await to_thread.run_sync(self._path.chmod, mode)

    @classmethod
    async def cwd(cls) -> 'Path':
        path = await to_thread.run_sync(pathlib.Path.cwd)
        return cls(path)

    async def exists(self) -> bool:
        return await to_thread.run_sync(self._path.exists, cancellable=True)

    async def expanduser(self) -> 'Path':
        return Path(await to_thread.run_sync(self._path.expanduser, cancellable=True))

    def glob(self, pattern: str) -> AsyncIterator['Path']:
        gen = self._path.glob(pattern)
        return _PathIterator(gen)

    async def group(self) -> str:
        return await to_thread.run_sync(self._path.group, cancellable=True)

    async def hardlink_to(self, target: Union[str, pathlib.Path, 'Path']) -> None:
        if isinstance(target, Path):
            target = target._path

        await to_thread.run_sync(self.hardlink_to, target)

    @classmethod
    async def home(cls) -> 'Path':
        home_path = await to_thread.run_sync(pathlib.Path.home)
        return cls(home_path)

    def is_absolute(self) -> bool:
        return self._path.is_absolute()

    async def is_block_device(self) -> bool:
        return await to_thread.run_sync(self._path.is_block_device, cancellable=True)

    async def is_char_device(self) -> bool:
        return await to_thread.run_sync(self._path.is_char_device, cancellable=True)

    async def is_dir(self) -> bool:
        return await to_thread.run_sync(self._path.is_dir, cancellable=True)

    async def is_fifo(self) -> bool:
        return await to_thread.run_sync(self._path.is_fifo, cancellable=True)

    async def is_file(self) -> bool:
        return await to_thread.run_sync(self._path.is_file, cancellable=True)

    async def is_mount(self) -> bool:
        return await to_thread.run_sync(self._path.is_mount, cancellable=True)

    def is_reserved(self) -> bool:
        return self._path.is_reserved()

    async def is_socket(self) -> bool:
        return await to_thread.run_sync(self._path.is_socket, cancellable=True)

    async def is_symlink(self) -> bool:
        return await to_thread.run_sync(self._path.is_symlink, cancellable=True)

    def iterdir(self) -> AsyncIterator['Path']:
        gen = self._path.iterdir()
        return _PathIterator(gen)

    def joinpath(self, *args: Union[str, 'PathLike[str]']) -> 'Path':
        return Path(self._path.joinpath(*args))

    async def lchmod(self, mode: int) -> None:
        await to_thread.run_sync(self.lchmod, mode)

    async def lstat(self) -> os.stat_result:
        return await to_thread.run_sync(self._path.lstat, cancellable=True)

    async def mkdir(self, mode: int = 0o777, parents: bool = False,
                    exist_ok: bool = False) -> None:
        await to_thread.run_sync(self._path.mkdir, mode, parents, exist_ok)

    async def open(self, mode: str = 'r', buffering: int = -1, encoding: Optional[str] = None,
                   errors: Optional[str] = None, newline: Optional[str] = None) -> AsyncFile:
        fp = await to_thread.run_sync(self._path.open, mode, buffering, encoding, errors, newline)
        return AsyncFile(fp)

    async def owner(self) -> str:
        return await to_thread.run_sync(self._path.owner, cancellable=True)

    async def read_bytes(self) -> bytes:
        return await to_thread.run_sync(self._path.read_bytes)

    async def read_text(self, encoding: Optional[str] = None, errors: Optional[str] = None) -> str:
        return await to_thread.run_sync(self._path.read_text, encoding, errors)

    def relative_to(self, *other: Union['Path', PathLike]) -> 'Path':
        other = tuple((p._path if isinstance(p, Path) else p) for p in other)
        return Path(self._path.relative_to(*other))

    async def rename(self, target: Union[str, pathlib.PurePath, 'Path']) -> None:
        if isinstance(target, Path):
            target = target._path

        await to_thread.run_sync(self._path.rename, target)

    async def replace(self, target: Union[str, pathlib.PurePath, 'Path']) -> None:
        if isinstance(target, Path):
            target = target._path

        await to_thread.run_sync(self._path.replace, target)

    async def resolve(self) -> 'Path':
        return Path(await to_thread.run_sync(self._path.resolve, cancellable=True))

    def rglob(self, pattern: str) -> AsyncIterator['Path']:
        gen = self._path.rglob(pattern)
        return _PathIterator(gen)

    async def rmdir(self) -> None:
        await to_thread.run_sync(self._path.rmdir)

    if sys.version_info >= (3, 10):
        async def stat(self, *, follow_symlinks: bool = True) -> os.stat_result:
            func = partial(self._path.stat, follow_symlinks=follow_symlinks)
            return await to_thread.run_sync(func, cancellable=True)
    else:
        async def stat(self) -> os.stat_result:
            return await to_thread.run_sync(self._path.stat, cancellable=True)

    async def symlink_to(self, target: Union[str, pathlib.Path, 'Path'],
                         target_is_directory: bool = False) -> None:
        if isinstance(target, Path):
            target = target._path

        await to_thread.run_sync(self.symlink_to, target, target_is_directory)

    async def touch(self, mode: int = 0o777, exist_ok: bool = True) -> None:
        await to_thread.run_sync(self._path.touch, mode, exist_ok)

    async def unlink(self, missing_ok: bool = False) -> None:
        await to_thread.run_sync(self._path.unlink, missing_ok)

    async def samefile(self, other_path: Union[str, bytes, int, pathlib.Path, 'Path']) -> bool:
        if isinstance(other_path, Path):
            other_path = other_path._path

        return await to_thread.run_sync(self._path.samefile, other_path, cancellable=True)

    def with_name(self, name: str) -> 'Path':
        return Path(self._path.with_name(name))

    def with_stem(self, stem: str) -> 'Path':
        return Path(self._path.with_stem(stem))

    def with_suffix(self, suffix: str) -> 'Path':
        return Path(self._path.with_suffix(suffix))

    async def write_bytes(self, data: bytes) -> int:
        return await to_thread.run_sync(self._path.write_bytes, data)

    async def write_text(self, data: str, encoding: Optional[str] = None,
                         errors: Optional[str] = None) -> int:
        return await to_thread.run_sync(self._path.write_text, data, encoding, errors)
