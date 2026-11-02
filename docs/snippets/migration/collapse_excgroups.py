import sys
from collections.abc import Generator
from contextlib import contextmanager

has_exceptiongroups = True
if sys.version_info < (3, 11):
    try:
        from exceptiongroup import BaseExceptionGroup
    except ImportError:
        has_exceptiongroups = False


@contextmanager
def collapse_excgroups() -> Generator[None, None, None]:
    try:
        yield
    except BaseException as exc:
        if has_exceptiongroups:
            while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
                exc = exc.exceptions[0]

        raise exc
