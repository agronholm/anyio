from typing import Sequence


class ExceptionGroup(Exception):
    """Raised when multiple exceptions have been raised in a task group."""

    def __init__(self, exceptions: Sequence[BaseException]) -> None:
        super().__init__(exceptions)

        self.msg = ''
        for i, exc in enumerate(exceptions, 1):
            if i > 1:
                self.msg += '\n\n'

            self.msg += 'Details of embedded exception {}:\n\n  {}: {}'.format(
                i, exc.__class__.__name__, exc)

    @property
    def exceptions(self) -> Sequence[BaseException]:
        return self.args[0]

    def __str__(self):
        return ', '.join('{}{}'.format(exc.__class__.__name__, exc.args) for exc in self.args[0])

    def __repr__(self) -> str:
        return '<{}: {}>'.format(self.__class__.__name__,
                                 ', '.join(repr(exc) for exc in self.args[0]))


class CancelledError(Exception):
    """Raised when the enclosing cancel scope has been cancelled."""


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
        super().__init__('The delimiter was not found among the first {} bytes'.format(max_bytes))


class ClosedResourceError(Exception):
    """Raised when a resource is closed by another task."""


class TLSRequired(Exception):
    """Raised when a TLS related stream method is called before the TLS handshake has been done."""
