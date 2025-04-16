from __future__ import annotations

from abc import abstractmethod
from contextlib import AbstractAsyncContextManager, AbstractContextManager
from inspect import isasyncgen, iscoroutine, isgenerator
from types import TracebackType
from typing import Generic, TypeVar, final

_T_co = TypeVar("_T_co", covariant=True)


class ContextManagerMixin(Generic[_T_co]):
    """
    Mixin class providing context manager functionality via a generator-based
    implementation.

    This class allows you to implement a context manager via :meth:`__contextmanager__`
    which should return a generator. The mechanics are meant to mirror those of
    :func:`@contextmanager <contextlib.contextmanager>`.

    .. note:: Classes using this mix-in are not reentrant as context managers, meaning
        that once you enter it, you can't re-enter before first exiting it.
    """

    __cm: AbstractContextManager[_T_co] | None = None

    @final
    def __enter__(self) -> _T_co:
        if self.__cm is not None:
            raise RuntimeError(
                f"this {self.__class__.__qualname__} has already been entered"
            )

        cm = self.__contextmanager__()
        if not isinstance(cm, AbstractContextManager):
            if isgenerator(cm):
                raise TypeError(
                    "__contextmanager__() returned a generator object instead of "
                    "a context manager. Did you forget to add the @contextmanager "
                    "decorator?"
                )

            raise TypeError(
                f"__contextmanager__() did not return a context manager object, "
                f"but {cm.__class__!r}"
            )

        if cm is self:
            raise TypeError(
                f"{self.__class__.__qualname__}.__contextmanager__() returned "
                f"self. Did you forget to add the @contextmanager decorator and a "
                f"'yield' statement?"
            )

        value = cm.__enter__()
        self.__cm = cm
        return value

    @final
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        if self.__cm is None:
            raise RuntimeError(
                f"this {self.__class__.__qualname__} has not been entered yet"
            )

        # Prevent circular references
        cm = self.__cm
        del self.__cm

        return cm.__exit__(exc_type, exc_val, exc_tb)

    @abstractmethod
    def __contextmanager__(self) -> AbstractContextManager[_T_co]:
        """
        Implement your context manager logic here.

        This method **must** be decorated with
        :func:`@contextmanager <contextlib.contextmanager>`.

        .. note:: Remember that the ``yield`` will raise any exception raised in the
            enclosed context block, so use a ``finally:`` block to clean up resources!

        :return: a context manager object
        """


class AsyncContextManagerMixin(Generic[_T_co]):
    """
    Mixin class providing async context manager functionality via a generator-based
    implementation.

    This class allows you to implement a context manager via
    :meth:`__asynccontextmanager__`. The mechanics are meant to mirror those of
    :func:`@asynccontextmanager <contextlib.asynccontextmanager>`.

    .. note:: Classes using this mix-in are not reentrant as context managers, meaning
        that once you enter it, you can't re-enter before first exiting it.
    """

    __cm: AbstractAsyncContextManager[_T_co] | None = None

    @final
    async def __aenter__(self) -> _T_co:
        if self.__cm is not None:
            raise RuntimeError(
                f"this {self.__class__.__qualname__} has already been entered"
            )

        cm = self.__asynccontextmanager__()
        if not isinstance(cm, AbstractAsyncContextManager):
            if isasyncgen(cm):
                raise TypeError(
                    "__asynccontextmanager__() returned an async generator instead of "
                    "an async context manager. Did you forget to add the "
                    "@asynccontextmanager decorator?"
                )
            elif iscoroutine(cm):
                cm.close()
                raise TypeError(
                    "__asynccontextmanager__() returned a coroutine object instead of "
                    "an async context manager. Did you forget to add the "
                    "@asynccontextmanager decorator and a 'yield' statement?"
                )

            raise TypeError(
                f"__asynccontextmanager__() did not return an async context manager, "
                f"but {cm.__class__!r}"
            )

        if cm is self:
            raise TypeError(
                f"{self.__class__.__qualname__}.__asynccontextmanager__() returned "
                f"self. Did you forget to add the @asynccontextmanager decorator and a "
                f"'yield' statement?"
            )

        value = await cm.__aenter__()
        self.__cm = cm
        return value

    @final
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        if self.__cm is None:
            raise RuntimeError(
                f"this {self.__class__.__qualname__} has not been entered yet"
            )

        # Prevent circular references
        cm = self.__cm
        del self.__cm

        return await cm.__aexit__(exc_type, exc_val, exc_tb)

    @abstractmethod
    def __asynccontextmanager__(self) -> AbstractAsyncContextManager[_T_co]:
        """
        Implement your async context manager logic here.

        This method **must** be decorated with
        :func:`@asynccontextmanager <contextlib.asynccontextmanager>`.

        .. note:: Remember that the ``yield`` will raise any exception raised in the
            enclosed context block, so use a ``finally:`` block to clean up resources!

        :return: an async context manager object
        """
