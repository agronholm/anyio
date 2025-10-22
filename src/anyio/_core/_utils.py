from __future__ import annotations

import sys
from collections.abc import AsyncGenerator, Callable
from contextlib import AbstractAsyncContextManager, asynccontextmanager
from dataclasses import dataclass
from functools import wraps
from types import TracebackType
from typing import overload

from anyio import Lock, create_memory_object_stream, create_task_group
from anyio.abc import TaskStatus
from anyio.streams.memory import MemoryObjectReceiveStream, MemoryObjectSendStream

if sys.version_info >= (3, 13):
    from typing import TypeVar
else:
    from typing_extensions import TypeVar

if sys.version_info < (3, 11):
    from exceptiongroup import BaseExceptionGroup

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

YieldT_co = TypeVar("YieldT_co", covariant=True)
SendT_contra = TypeVar("SendT_contra", contravariant=True, default=None)
P = ParamSpec("P")


@dataclass(frozen=True)
class _ExceptionWrapper:
    exc: BaseException


class _GeneratorRunner(AsyncGenerator[YieldT_co, SendT_contra]):
    __slots__ = (
        "_asyncgen",
        "_send_to_asyncgen",
        "_receive_from_asyncgen",
        "_lock",
        "_exc",
        "_item",
    )

    _send_to_asyncgen: MemoryObjectSendStream[SendT_contra | _ExceptionWrapper | None]
    _receive_from_asyncgen: MemoryObjectReceiveStream[YieldT_co | _ExceptionWrapper]

    def __init__(self, asyncgen: AsyncGenerator[YieldT_co, SendT_contra]) -> None:
        self._asyncgen = asyncgen
        self._lock = Lock()
        self._exc: BaseException | None = None

    def __aiter__(self) -> AsyncGenerator[YieldT_co, SendT_contra]:
        return self

    async def __anext__(self) -> YieldT_co:
        return await self._send_item_to_asyncgen(None)

    async def _send_item_to_asyncgen(
        self, item: SendT_contra | _ExceptionWrapper | None
    ) -> YieldT_co:
        async with self._lock:
            await self._send_to_asyncgen.send(item)
            received_item = await self._receive_from_asyncgen.receive()
            if isinstance(received_item, _ExceptionWrapper):
                raise received_item.exc from None
            else:
                return received_item

    async def asend(self, item: SendT_contra) -> YieldT_co:
        return await self._send_item_to_asyncgen(item)

    @overload
    async def athrow(
        self,
        typ: type[BaseException],
        val: BaseException | object = None,
        tb: TracebackType | None = None,
        /,
    ) -> YieldT_co: ...

    @overload
    async def athrow(
        self, typ: BaseException, val: None = None, tb: TracebackType | None = None, /
    ) -> YieldT_co: ...

    async def athrow(
        self,
        typ: type[BaseException] | BaseException,
        val: BaseException | object | None = None,
        tb: TracebackType | None = None,
        /,
    ) -> YieldT_co:
        if isinstance(val, BaseException):
            exc = val
        elif isinstance(typ, BaseException):
            exc = typ
        else:
            exc = typ(val) if val is not None else typ()

        return await self._send_item_to_asyncgen(_ExceptionWrapper(exc))

    async def aclose(self) -> None:
        async with self._lock:
            self._send_to_asyncgen.close()

    async def _run(self, *, task_status: TaskStatus) -> None:
        try:
            self._send_to_asyncgen, receive_from_outside = create_memory_object_stream[
                "SendT_contra | _ExceptionWrapper | None"
            ]()
            send_to_outside, self._receive_from_asyncgen = create_memory_object_stream[
                "YieldT_co | _ExceptionWrapper"
            ]()
            with receive_from_outside, send_to_outside:
                task_status.started()
                async for item_to_send in receive_from_outside:
                    try:
                        if isinstance(item_to_send, _ExceptionWrapper):
                            item_from_agen = await self._asyncgen.athrow(
                                item_to_send.exc
                            )
                        elif item_to_send is None:
                            item_from_agen = await self._asyncgen.__anext__()
                        else:
                            item_from_agen = await self._asyncgen.asend(item_to_send)
                    except BaseException as exc:
                        send_to_outside.send_nowait(_ExceptionWrapper(exc))
                        if not isinstance(exc, Exception):
                            raise
                        else:
                            return
                    else:
                        await send_to_outside.send(item_from_agen)
        finally:
            await self._asyncgen.aclose()


@asynccontextmanager
async def _wrap_asyncgen(
    asyncgen: AsyncGenerator[YieldT_co, SendT_contra],
) -> AsyncGenerator[AsyncGenerator[YieldT_co, SendT_contra]]:
    try:
        async with create_task_group() as tg:
            runner = _GeneratorRunner(asyncgen)
            await tg.start(runner._run)
            yield runner
            tg.cancel_scope.cancel()
    except BaseExceptionGroup as excgrp:
        if len(excgrp.exceptions) == 1:
            raise excgrp.exceptions[0] from None
        else:
            raise


def safe_asyncgen(
    func: Callable[P, AsyncGenerator[YieldT_co, SendT_contra]],
) -> Callable[P, AbstractAsyncContextManager[AsyncGenerator[YieldT_co, SendT_contra]]]:
    @wraps(func)
    def wrapper(
        *args: P.args, **kwargs: P.kwargs
    ) -> AbstractAsyncContextManager[AsyncGenerator[YieldT_co, SendT_contra]]:
        return _wrap_asyncgen(func(*args, **kwargs))

    return wrapper
