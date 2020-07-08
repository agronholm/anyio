from traceback import format_exception
from typing import Sequence


class ExceptionGroup(BaseException):
    """Raised when multiple exceptions have been raised in a task group."""

    SEPARATOR = '----------------------------\n'

    exceptions: Sequence[BaseException]

    def __str__(self):
        tracebacks = ['\n'.join(format_exception(type(exc), exc, exc.__traceback__))
                      for exc in self.exceptions]
        return f'{len(self.exceptions)} exceptions were raised in the task group:\n' \
               f'{self.SEPARATOR}{self.SEPARATOR.join(tracebacks)}'

    def __repr__(self) -> str:
        return f'<{self.__class__.__name__} ({len(self.exceptions)} exceptions)>'


class IncompleteRead(Exception):
    """"
    Raised during ``read_exactly()`` if the connection is closed before the requested amount of
    bytes has been read.

    :ivar bytes data: bytes read before the stream was closed
    """

    def __init__(self) -> None:
        super().__init__('The stream was closed before the read operation could be completed')


class DelimiterNotFound(Exception):
    """
    Raised during ``read_until()`` if the maximum number of bytes has been read without the
    delimiter being found.

    :ivar bytes data: bytes read before giving up
    """

    def __init__(self, max_bytes: int) -> None:
        super().__init__(f'The delimiter was not found among the first {max_bytes} bytes')


class ClosedResourceError(Exception):
    """Raised when trying to use a resource that has been closed."""


class BrokenResourceError(Exception):
    """
    Raised when trying to use a resource that has been rendered unusuable due to external causes
    (e.g. a send stream whose peer has disconnected).
    """


class EndOfStream(Exception):
    """Raised when trying to read from a stream that has been closed from the other end."""


class TLSRequired(Exception):
    """Raised when a TLS related stream method is called before the TLS handshake has been done."""


class ResourceBusyError(Exception):
    """Raised when two tasks are trying to read from or write to the same resource concurrently."""

    def __init__(self, action: str):
        super().__init__(f'Another task is already {action} this resource')


class WouldBlock(Exception):
    """Raised by ``X_nowait``functions if ``X()``would block."""
