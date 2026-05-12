from __future__ import annotations

from collections.abc import Generator
from enum import Enum, auto
from typing import Any, Generic, TypeVar

from ._eventloop import get_cancelled_exc_class
from ._exceptions import (
    FutureAlreadyFinished,
    FutureCancelled,
    TaskFailed,
    TaskNotFinished,
)
from ._synchronization import Event
from ._tasks import CancelScope

T = TypeVar("T")


class Future(Generic[T]):
    class Status(Enum):
        """The status of a future handle."""

        PENDING = auto()
        FINISHED = auto()
        FAILED = auto()
        CANCELLING = auto()
        CANCELLED = auto()

    __slots__ = (
        "_result_value",
        "_finished_event",
        "_cancel_scope",
        "_exception",
        "_name",
    )
    _result_value: T

    def __init__(self, *, name: str | None = None) -> None:
        self._finished_event = Event()
        self._cancel_scope = CancelScope()
        self._exception: BaseException | None = None
        self._name = name

    def _check_status(self) -> None:
        match self.status:
            case Future.Status.PENDING:
                return
            case Future.Status.FINISHED:
                raise FutureAlreadyFinished("future has already finished")
            case Future.Status.FAILED:
                raise FutureAlreadyFinished("future already failed")
            case Future.Status.CANCELLING:
                raise FutureCancelled("future was cancelled")
            case Future.Status.CANCELLED:
                raise FutureCancelled("future was cancelled") from self._exception

    async def wait(self) -> None:
        """
        Waits for the future to finish.

        This method will attempt to wait for a result or exception
        """
        with self._cancel_scope:
            try:
                await self._finished_event.wait()
            except BaseException as e:
                self._exception = e
                raise
            finally:
                self._finished_event.set()

    def set_result(self, value: T) -> None:
        """Send pending result for a container object"""
        self._check_status()
        self._result_value = value
        self._finished_event.set()

    def set_exception(self, exception: BaseException) -> None:
        """Send exception result for a container object"""
        self._check_status()
        self._exception = exception
        self._finished_event.set()

    def cancel(self) -> None:
        match self.status:
            case Future.Status.PENDING:
                return self._cancel_scope.cancel()
            case Future.Status.FINISHED:
                raise FutureAlreadyFinished("future has already finished")
            case Future.Status.FAILED:
                raise FutureAlreadyFinished("future already failed")
            case Future.Status.CANCELLING:
                return
            case Future.Status.CANCELLED:
                return


    @property
    def exception(self) -> BaseException | None:
        match self.status:
            case Future.Status.PENDING:
                raise TaskNotFinished("the future has not finished yet")
            case Future.Status.FINISHED:
                return None
            case Future.Status.CANCELLING:
                raise FutureCancelled("the future was cancelled")
            case Future.Status.CANCELLED:
                raise FutureCancelled("the future was cancelled") from self._exception
            case Future.Status.FAILED:
                return self._exception

    @property
    def return_value(self) -> T:
        """
        The return value of the future.

        :raises TaskNotFinished: if the future has not finished yet
        :raises FutureCancelled: if the future was cancelled
        :raises TaskFailed: if the future raised an exception

        """
        match self.status:
            case Future.Status.PENDING:
                raise TaskNotFinished("the future has not finished yet")
            case Future.Status.FINISHED:
                return self._result_value
            case Future.Status.CANCELLING:
                raise FutureCancelled("the future was cancelled")
            case Future.Status.CANCELLED:
                raise FutureCancelled("the future was cancelled") from self._exception
            case Future.Status.FAILED:
                raise TaskFailed("the future raised an exception") from self._exception

    @property
    def status(self) -> Future.Status:
        if not self._finished_event.is_set():
            if self._cancel_scope.cancel_called:
                return Future.Status.CANCELLING
            else:
                return Future.Status.PENDING
        elif self._exception is not None:
            if isinstance(self._exception, get_cancelled_exc_class()):
                return Future.Status.CANCELLED
            else:
                return Future.Status.FAILED
        else:
            return Future.Status.FINISHED

    def __await__(self) -> Generator[Any, Any, T]:
        yield from self.wait().__await__()
        return self.return_value

    def __repr__(self) -> str:
        return (
            f"<{self.__class__.__name__} {self.status.name.lower()} "
            f"name={self._name!r}>"
        )
