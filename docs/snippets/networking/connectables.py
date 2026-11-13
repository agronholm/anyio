from os import PathLike
from ssl import SSLContext
from types import TracebackType
from typing import Self

from anyio import as_connectable
from anyio.abc import ByteStreamConnectable


class MyNetworkClient:
    def __init__(
        self,
        connectable: (
            ByteStreamConnectable | tuple[str, int] | str | bytes | PathLike[str]
        ),
        tls: bool = False,
        ssl_context: SSLContext | None = None,
    ) -> None:
        self.connectable = as_connectable(connectable, tls=tls, ssl_context=ssl_context)

    async def __aenter__(self) -> Self:
        # Connect to the remote and enter the stream's context manager
        self._stream = await self.connectable.connect()
        await self._stream.__aenter__()
        return self

    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> None:
        # Exit the stream's context manager, thus disconnecting it
        await self._stream.__aexit__(exc_type, exc_val, exc_tb)
