import os
from typing import Union, Optional

import anyio


class AsyncFile:
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

        async with await anyio.open_file(...) as f:
            async for line in f:
                print(line)
    """

    def __init__(self, fp) -> None:
        self._fp = fp

    def __getattr__(self, name):
        return getattr(self._fp, name)

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.aclose()

    @property
    def wrapped(self):
        return self._fp

    async def __aiter__(self):
        while True:
            line = await self.readline()
            if line:
                yield line
            else:
                break

    async def aclose(self) -> None:
        return await anyio.run_sync_in_worker_thread(self._fp.close)

    async def read(self, size: int = -1) -> Union[bytes, str]:
        return await anyio.run_sync_in_worker_thread(self._fp.read, size)

    async def read1(self, size: int = -1) -> Union[bytes, str]:
        return await anyio.run_sync_in_worker_thread(self._fp.read1, size)

    async def readline(self) -> bytes:
        return await anyio.run_sync_in_worker_thread(self._fp.readline)

    async def readlines(self) -> bytes:
        return await anyio.run_sync_in_worker_thread(self._fp.readlines)

    async def readinto(self, b: Union[bytes, memoryview]) -> bytes:
        return await anyio.run_sync_in_worker_thread(self._fp.readinto, b)

    async def readinto1(self, b: Union[bytes, memoryview]) -> bytes:
        return await anyio.run_sync_in_worker_thread(self._fp.readinto1, b)

    async def write(self, b: bytes) -> None:
        return await anyio.run_sync_in_worker_thread(self._fp.write, b)

    async def writelines(self, lines: bytes) -> None:
        return await anyio.run_sync_in_worker_thread(self._fp.writelines, lines)

    async def truncate(self, size: Optional[int] = None) -> int:
        return await anyio.run_sync_in_worker_thread(self._fp.truncate, size)

    async def seek(self, offset: int, whence: Optional[int] = os.SEEK_SET) -> int:
        return await anyio.run_sync_in_worker_thread(self._fp.seek, offset, whence)

    async def tell(self) -> int:
        return await anyio.run_sync_in_worker_thread(self._fp.tell)

    async def flush(self) -> None:
        return await anyio.run_sync_in_worker_thread(self._fp.flush)
