from __future__ import annotations

import asyncio
import socket
import threading
from collections.abc import Callable
from selectors import EVENT_READ, EVENT_WRITE, DefaultSelector
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from _typeshed import FileDescriptorLike

_selector_lock = threading.Lock()
_selector: Selector | None = None


class Selector:
    def __init__(self) -> None:
        self._thread = threading.Thread(target=self.run)
        self._selector = DefaultSelector()
        self._send, self._receive = socket.socketpair()
        self._selector.register(self._receive, EVENT_READ)
        self._closed = False

    def start(self) -> None:
        self._thread.start()
        threading._register_atexit(self._stop)  # type: ignore[attr-defined]

    def _stop(self) -> None:
        global _selector
        self._closed = True
        self._send.send(b"\x00")
        self._send.close()
        self._thread.join()
        _selector = None
        assert (
            not self._selector.get_map()
        ), "selector still has registered file descriptors after shutdown"

    def add_reader(self, fd: FileDescriptorLike, callback: Callable[[], Any]) -> None:
        loop = asyncio.get_running_loop()
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, EVENT_READ, {EVENT_READ: (loop, callback)})
        else:
            if EVENT_READ in key.data:
                raise ValueError(
                    "this file descriptor is already registered for reading"
                )

            key.data[EVENT_READ] = loop, callback
            self._selector.modify(fd, key.events | EVENT_READ, key.data)

        self._send.send(b"\x00")

    def add_writer(self, fd: FileDescriptorLike, callback: Callable[[], Any]) -> None:
        loop = asyncio.get_running_loop()
        try:
            key = self._selector.get_key(fd)
        except KeyError:
            self._selector.register(fd, EVENT_WRITE, {EVENT_WRITE: (loop, callback)})
        else:
            if EVENT_WRITE in key.data:
                raise ValueError(
                    "this file descriptor is already registered for writing"
                )

            key.data[EVENT_WRITE] = loop, callback
            self._selector.modify(fd, key.events | EVENT_WRITE, key.data)

        self._send.send(b"\x00")

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
        while not self._closed:
            for key, events in self._selector.select():
                if key.fileobj is self._receive:
                    self._receive.recv(10240)
                    continue

                if events & EVENT_READ:
                    loop, callback = key.data
                    self.remove_reader(key.fd)
                    try:
                        loop.call_soon_threadsafe(callback)
                    except RuntimeError:
                        pass  # the loop was already closed

                if events & EVENT_WRITE:
                    loop, callback = key.data
                    self.remove_writer(key.fd)
                    try:
                        loop.call_soon_threadsafe(callback)
                    except RuntimeError:
                        pass  # the loop was already closed

        self._selector.unregister(self._receive)
        self._receive.close()


def get_selector() -> Selector:
    with _selector_lock:
        if _selector is None:
            selector = Selector()
            selector.start()

        return selector
