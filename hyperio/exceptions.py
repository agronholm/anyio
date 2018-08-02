from typing import Sequence


class MultiError(Exception):
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


class DelimiterNotFound(Exception):
    pass
