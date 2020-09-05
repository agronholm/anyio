from abc import ABCMeta, abstractmethod
from typing import Any, Awaitable, Callable, Dict


class TestRunner(metaclass=ABCMeta):
    """
    Encapsulates a running event loop. Every call made through this object will use the same event
    loop.
    """

    def __enter__(self) -> 'TestRunner':
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.close()

    @abstractmethod
    def close(self) -> None:
        """Close the event loop."""

    @abstractmethod
    def call(self, func: Callable[..., Awaitable], *args: tuple, **kwargs: Dict[str, Any]):
        """
        Call the given function within the backend's event loop.

        :param func: a callable returning an awaitable
        :param args: positional arguments to call ``func`` with
        :param kwargs: keyword arguments to call ``func`` with
        :return: the return value of ``func``
        """
