"""
Waiting for a child process to exit on Windows, independently of the event loop
implementation in use (stdlib ``ProactorEventLoop``, winloop, ``SelectorEventLoop`` …).

This uses ``RegisterWaitForSingleObject``, which signals completion from a Windows thread
pool thread (i.e. without tying up a Python thread), and wakes the running event loop via
:meth:`~asyncio.loop.call_soon_threadsafe`.
"""

from __future__ import annotations

import asyncio
import ctypes
import sys
from ctypes import wintypes
from typing import TYPE_CHECKING

# This module is only ever imported on Windows; the assertion lets type checkers on other
# platforms skip it (mirrors the pattern used by Trio's Windows-only modules).
assert sys.platform == "win32" or not TYPE_CHECKING

kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)

SYNCHRONIZE = 0x00100000
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
INFINITE = 0xFFFFFFFF
WT_EXECUTEONLYONCE = 0x00000008

_WAIT_CALLBACK = ctypes.WINFUNCTYPE(None, wintypes.LPVOID, wintypes.BOOLEAN)

kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
kernel32.OpenProcess.restype = wintypes.HANDLE

kernel32.RegisterWaitForSingleObject.argtypes = [
    ctypes.POINTER(wintypes.HANDLE),
    wintypes.HANDLE,
    _WAIT_CALLBACK,
    wintypes.LPVOID,
    wintypes.DWORD,
    wintypes.DWORD,
]
kernel32.RegisterWaitForSingleObject.restype = wintypes.BOOL

kernel32.UnregisterWait.argtypes = [wintypes.HANDLE]
kernel32.UnregisterWait.restype = wintypes.BOOL

kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
kernel32.CloseHandle.restype = wintypes.BOOL


class _ProcessWaiter:
    def __init__(self, loop: asyncio.AbstractEventLoop, process_handle: int) -> None:
        self._loop = loop
        self._process_handle = process_handle
        self._wait_handle = wintypes.HANDLE()
        self._future: asyncio.Future[None] = loop.create_future()
        # Keep the ctypes callback alive for as long as Windows may call it
        self._callback = _WAIT_CALLBACK(self._on_signalled)

    def start(self) -> asyncio.Future[None]:
        if not kernel32.RegisterWaitForSingleObject(
            ctypes.byref(self._wait_handle),
            self._process_handle,
            self._callback,
            None,
            INFINITE,
            WT_EXECUTEONLYONCE,
        ):
            raise ctypes.WinError(ctypes.get_last_error())

        return self._future

    def _on_signalled(self, context: object, timed_out: bool) -> None:
        # This runs on a Windows thread pool thread
        self._loop.call_soon_threadsafe(self._complete)

    def _complete(self) -> None:
        if not self._future.done():
            self._future.set_result(None)


async def wait_for_pid(pid: int) -> None:
    """Wait until the process with the given PID has exited."""
    process_handle = kernel32.OpenProcess(
        SYNCHRONIZE | PROCESS_QUERY_LIMITED_INFORMATION, False, pid
    )
    if not process_handle:
        raise ctypes.WinError(ctypes.get_last_error())

    waiter = _ProcessWaiter(asyncio.get_running_loop(), process_handle)
    try:
        await waiter.start()
    finally:
        if waiter._wait_handle:
            kernel32.UnregisterWait(waiter._wait_handle)

        kernel32.CloseHandle(process_handle)
