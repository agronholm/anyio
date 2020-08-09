from typing import AsyncContextManager, AsyncIterator

from ._eventloop import get_asynclib


def open_signal_receiver(*signals: int) -> AsyncContextManager[AsyncIterator[int]]:
    """
    Start receiving operating system signals.

    :param signals: signals to receive (e.g. ``signal.SIGINT``)
    :return: an asynchronous context manager for an asynchronous iterator which yields signal
        numbers

    .. warning:: Windows does not support signals natively so it is best to avoid relying on this
        in cross-platform applications.

    """
    return get_asynclib().open_signal_receiver(*signals)
