from collections.abc import Generator
from contextlib import contextmanager


@contextmanager
def collapse_excgroups() -> Generator[None, None, None]:
    try:
        yield
    except BaseException as exc:
        while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
            exc = exc.exceptions[0]

        raise exc
