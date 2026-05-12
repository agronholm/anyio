from __future__ import annotations

import sys
from collections.abc import Awaitable, Callable, Generator
from enum import Enum, auto
from typing import Any, TypeVar

from .. import Event
from ..lowlevel import RunVar
from ._exceptions import FutureAlreadyFinished, FutureCancelled, FutureNotFinished

if sys.version_info >= (3, 11):
    from typing import Self
else:
    from typing_extensions import Self


T = TypeVar("T")

class Future(Awaitable[T]):
    """A asynchronous container object for waiting on single objects to be completed."""
    class Status(Enum):
        PENDING = auto()
        CANCELLED = auto()
        FINISHED = auto()

    def __init__(self) -> None:
        self._event = Event()
        self._state = self.Status.PENDING
        self._result: T = None
        self._exception: BaseException | None = None
        self._cancelled_exc: BaseException | None = None

        self._done_callbacks: list[tuple[RunVar[Any] | None , Callable[[Self], Any]]] = []
        self._cancel_msg = None

    def __check_not_done(self) -> None:
        if self._state != self.Status.PENDING:
            raise FutureAlreadyFinished("Future has already finished.")

    def __check_done(self) -> None:
        if self._state == self.Status.CANCELLED:
            exc = self._make_cancelled_error()
            raise exc
        if self._state != self.Status.FINISHED:
            raise FutureNotFinished("Result is not ready.")

    def __schedule_callbacks(self) -> None:
        # set event so that anything awaiting this object
        # can be notified that it is now ready for use.
        self._event.set()
        for rv, cb in self._done_callbacks:
            if rv:
                with rv:
                    cb(self)
            else:
                cb(self)

    def cancel(self, msg=None) -> bool:
        """Cancel the future and schedules callbacks"""
        if self._state != self.Status.PENDING:
            return False
        self._state = self.Status.CANCELLED
        self._cancel_msg = msg
        self.__schedule_callbacks()
        return True

    def done(self) -> bool:
        """Return True if future was completed."""
        return self._state != self.Status.PENDING

    def cancelled(self):
        """Return True if future was cancelled."""
        return self._state != self.Status.CANCELLED

    def _make_cancelled_error(self) -> FutureCancelled:
        """Creates a :class:`.FutureCancelled` exception."""
        if self._cancelled_exc is not None:
            exc = self._cancelled_exc
            self._cancelled_exc = None
            return exc

        exc = FutureCancelled() if self._cancel_msg is not None else FutureCancelled(self._cancel_msg)
        exc.__context__ = self._cancelled_exc
        self._cancelled_exc = None
        return exc

    def result(self) -> T:
        """Gets the result of a :class:`.Future` if completed."""
        self.__check_done()
        if self._exception is not None:
            raise self._exception
        return self._result

    def exception(self) -> BaseException | None:
        """Gets the exception of a :class:`.Future` if completed it will be done if there is instead a successful result."""
        self.__check_done()
        return self._exception

    def add_done_callback(self, fn: Callable[[Self], Any], *, context: RunVar[Self] | None = None) -> None:
        """Creates a synchronous callback for when a future is considered as being completed or not."""
        if self._state != self.Status.PENDING:
            if context:
                with context:
                    fn(self)
            else:
                fn(self)
        else:
            self._done_callbacks.append((context, fn))

    def remove_done_callback(self, fn: Callable[[Self], Any]):
        filtered_callbacks = [(f, ctx)
                              for (f, ctx) in self._done_callbacks
                              if f != fn]
        removed_count = len(self._done_callbacks) - len(filtered_callbacks)
        if removed_count:
            self._done_callbacks[:] = filtered_callbacks
        return removed_count

    def set_result(self, result: T) -> None:
        """sets the results of a :class:`.Future` object."""
        self.__check_not_done()
        self._result = result
        self._state = self.Status.FINISHED
        self.__schedule_callbacks()

    def set_exception(self, exception: BaseException) -> None:
        """sets the exception of a :class:`.Future` object."""
        self.__check_not_done()
        self._exception = exception
        self._state = self.Status.FINISHED
        self.__schedule_callbacks()

    # Mostly used as a proxy for awaiting on a pending object.
    async def wait(self) -> T:
        await self._event.wait()
        return self.result()

    def __await__(self) -> Generator[Any, None, T]:
        return self.wait().__await__()

def create_future() -> Future[T]:
    """Shortcut method for creating a new :class:`.Future` object."""
    return Future()
