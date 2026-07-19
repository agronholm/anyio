"""
A background event loop capable of overlapped (IOCP) pipe I/O, for use when the main
event loop can't do it itself (the Windows ``SelectorEventLoop``).

This mirrors :mod:`anyio._core._asyncio_selector_thread`: a single background thread runs
a ``ProactorEventLoop`` (or winloop) for the lifetime of the interpreter (shut down via
``threading._register_atexit``). Subprocess pipe operations are marshalled onto it with
:func:`asyncio.run_coroutine_threadsafe` and awaited on the caller's loop via
:func:`asyncio.wrap_future`.
"""

from __future__ import annotations

import asyncio
import sys
import threading
from collections.abc import Coroutine
from typing import TYPE_CHECKING, Any, TypeVar

from ..abc import ByteReceiveStream, ByteSendStream

assert sys.platform == "win32" or not TYPE_CHECKING

T = TypeVar("T")

_proactor_thread_lock = threading.Lock()
_proactor_thread: ProactorThread | None = None


def _new_proactor_loop() -> asyncio.AbstractEventLoop:
    try:
        import winloop
    except ImportError:
        return asyncio.ProactorEventLoop()
    else:
        return winloop.new_event_loop()


class ProactorThread:
    def __init__(self) -> None:
        self._loop = _new_proactor_loop()
        self._thread = threading.Thread(
            target=self._run, name="AnyIO proactor", daemon=True
        )
        self._started = threading.Event()

    def _run(self) -> None:
        asyncio.set_event_loop(self._loop)
        self._loop.call_soon(self._started.set)
        try:
            self._loop.run_forever()
        finally:
            self._loop.close()

    def start(self) -> None:
        self._thread.start()
        self._started.wait()
        threading._register_atexit(self._stop)  # type: ignore[attr-defined]

    def _stop(self) -> None:
        global _proactor_thread
        self._loop.call_soon_threadsafe(self._loop.stop)
        self._thread.join()
        _proactor_thread = None

    async def run(self, coro: Coroutine[Any, Any, T]) -> T:
        """Run ``coro`` on the proactor loop, awaiting the result on the caller's loop."""
        future = asyncio.run_coroutine_threadsafe(coro, self._loop)
        return await asyncio.wrap_future(future, loop=asyncio.get_running_loop())


class ProxyReceiveStream(ByteReceiveStream):
    """Forwards receive/aclose to a stream living on the proactor thread's loop."""

    def __init__(self, thread: ProactorThread, inner: ByteReceiveStream) -> None:
        self._thread = thread
        self._inner = inner

    async def receive(self, max_bytes: int = 65536) -> bytes:
        return await self._thread.run(self._inner.receive(max_bytes))

    async def aclose(self) -> None:
        await self._thread.run(self._inner.aclose())


class ProxySendStream(ByteSendStream):
    """Forwards send/aclose to a stream living on the proactor thread's loop."""

    def __init__(self, thread: ProactorThread, inner: ByteSendStream) -> None:
        self._thread = thread
        self._inner = inner

    async def send(self, item: bytes) -> None:
        await self._thread.run(self._inner.send(item))

    async def aclose(self) -> None:
        await self._thread.run(self._inner.aclose())


def get_proactor_thread() -> ProactorThread:
    global _proactor_thread

    with _proactor_thread_lock:
        if _proactor_thread is None:
            _proactor_thread = ProactorThread()
            _proactor_thread.start()

        return _proactor_thread
