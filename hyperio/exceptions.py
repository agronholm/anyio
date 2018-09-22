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
    pass


class IncompleteRead(Exception):
    def __init__(self, data: bytes, expected_bytes: int) -> None:
        super().__init__('Incomplete read ({} out of {} bytes read before the stream was closed)'
                         .format(len(data), expected_bytes))
        self.data = data


class DelimiterNotFound(Exception):
    def __init__(self, data: bytes, stream_closed: bool) -> None:
        reason = 'the stream was closed' if stream_closed else 'max_bytes was reached'
        super().__init__('Delimiter not found ({} bytes read before {}'.format(len(data), reason))
        self.data = data
