from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable
from selectors import EVENT_READ, EVENT_WRITE, DefaultSelector
from typing import TYPE_CHECKING, Any
from weakref import WeakKeyDictionary

if TYPE_CHECKING:
    from _typeshed import FileDescriptorLike

_selectors: WeakKeyDictionary[asyncio.AbstractEventLoop, Selector] = WeakKeyDictionary()


class Selector:
    def __init__(self, loop: asyncio.AbstractEventLoop):
        self._loop = loop
        self._thread = threading.Thread(target=self.run)
        self._selector = DefaultSelector()
        self._send, self._receive = socket.socketpair()
        self._notify_key = self._selector.register(self._receive, EVENT_READ)

    def start(self) -> None:
        from anyio._backends._asyncio import find_root_task

        find_root_task().add_done_callback(lambda task: self._stop())
        self._thread.start()

    def _stop(self) -> None:
        self._send.send(b"\x00")
        self._send.close()
        self._thread.join()
        del _selectors[self._loop]
        assert (
            not self._selector.get_map()
        ), "selector still has registered file descriptors after shutdown"

    def add_reader(self, fd: FileDescriptorLike, callback: Callable[[], Any]) -> None:
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, EVENT_READ, {EVENT_READ: callback})
        else:
            if EVENT_READ in key.data:
                raise ValueError(
                    "this file descriptor is already registered for reading"
                )

            key.data[EVENT_READ] = callback
            self._selector.modify(fd, key.events | EVENT_READ, key.data)

    def add_writer(self, fd: FileDescriptorLike, callback: Callable[[], Any]) -> None:
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, EVENT_WRITE, {EVENT_WRITE: callback})
        else:
            if EVENT_WRITE in key.data:
                raise ValueError(
                    "this file descriptor is already registered for writing"
                )

            key.data[EVENT_WRITE] = callback
            self._selector.modify(fd, key.events | EVENT_WRITE, key.data)

    def remove_reader(self, fd: FileDescriptorLike) -> bool:
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False

        if new_events := key.events ^ EVENT_READ:
            del key.data[EVENT_READ]
            self._selector.modify(fd, new_events)
        else:
            self._selector.unregister(fd)

        return True

    def remove_writer(self, fd: FileDescriptorLike) -> bool:
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            return False

        if new_events := key.events ^ EVENT_WRITE:
            del key.data[EVENT_WRITE]
            self._selector.modify(fd, new_events)
        else:
            self._selector.unregister(fd)

        return True

    def run(self) -> None:
        while True:
            for key, events in self._selector.select():
                if key is self._notify_key:
                    self._receive.close()
                    return

                if events & EVENT_READ and (callback := key.data.get(EVENT_READ)):
                    self._loop.call_soon_threadsafe(callback)

                if events & EVENT_WRITE and (callback := key.data.get(EVENT_WRITE)):
                    self._loop.call_soon_threadsafe(callback)


def get_selector(loop: asyncio.AbstractEventLoop) -> Selector:
    try:
        return _selectors[loop]
    except KeyError:
        _selectors[loop] = selector = Selector(asyncio.get_running_loop())
        selector.start()
        return selector
