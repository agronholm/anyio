from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator, Generator
from inspect import isasyncgen, iscoroutine
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
    """

    @final
    def __enter__(self) -> _T_co:
        gen = self.__contextmanager__()
        if not isinstance(gen, Generator):
            raise TypeError(
                f"__contextmanager__() did not return a generator object, "
                f"but {gen.__class__!r}"
            )

        try:
            value = gen.send(None)
        except StopIteration:
            raise RuntimeError(
                "the __contextmanager__() generator returned without yielding a value"
            ) from None

        self.__cm = gen
        return value

    @final
    def __exit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        # Prevent circular references
        cm = self.__cm
        del self.__cm

        if exc_val is not None:
            try:
                cm.throw(exc_val)
            except StopIteration:
                return True
        else:
            try:
                cm.send(None)
            except StopIteration:
                return None

        cm.close()
        raise RuntimeError("the __contextmanager__() generator didn't stop")

    @abstractmethod
    def __contextmanager__(self) -> Generator[_T_co, None, None]:
        """
        Implement your context manager logic here, as you would with
        :func:`@contextmanager <contextlib.contextmanager>`.

        Any code up to the ``yield`` will be run in ``__enter__()``, and any code after
        it is run in ``__exit__()``.

        .. note:: If an exception is raised in the context block, it is reraised from
            the ``yield``, just like with
            :func:`@contextmanager <contextlib.contextmanager>`.

        :return: a generator that yields exactly once
        """


class AsyncContextManagerMixin(Generic[_T_co]):
    """
    Mixin class providing async context manager functionality via a generator-based
    implementation.

    This class allows you to implement a context manager via
    :meth:`__asynccontextmanager__`. The mechanics are meant to mirror those of
    :func:`@asynccontextmanager <contextlib.asynccontextmanager>`.
    """

    @final
    async def __aenter__(self) -> _T_co:
        gen = self.__asynccontextmanager__()
        if not isasyncgen(gen):
            if iscoroutine(gen):
                gen.close()
                raise TypeError(
                    "__asynccontextmanager__() returned a coroutine object instead of "
                    "an async generator. Did you forget to add 'yield'?"
                )

            raise TypeError(
                f"__asynccontextmanager__() did not return an async generator object, "
                f"but {gen.__class__!r}"
            )

        try:
            value = await gen.asend(None)
        except StopAsyncIteration:
            raise RuntimeError(
                "the __asynccontextmanager__() generator returned without yielding a "
                "value"
            ) from None

        self.__cm = gen
        return value

    @final
    async def __aexit__(
        self,
        exc_type: type[BaseException] | None,
        exc_val: BaseException | None,
        exc_tb: TracebackType | None,
    ) -> bool | None:
        # Prevent circular references
        cm = self.__cm
        del self.__cm

        if exc_val is not None:
            try:
                await cm.athrow(exc_val)
            except StopAsyncIteration:
                return True
        else:
            try:
                await cm.asend(None)
            except StopAsyncIteration:
                return None

        await cm.aclose()
        raise RuntimeError("the __asynccontextmanager__() generator didn't stop")

    @abstractmethod
    def __asynccontextmanager__(self) -> AsyncGenerator[_T_co, None]:
        """
        Implement your async context manager logic here, as you would with
        :func:`@asynccontextmanager <contextlib.asynccontextmanager>`.

        Any code up to the ``yield`` will be run in ``__aenter__()``, and any code after
        it is run in ``__aexit__()``.

        .. note:: If an exception is raised in the context block, it is reraised from
            the ``yield``, just like with
            :func:`@asynccontextmanager <contextlib.asynccontextmanager>`.

        :return: an async generator that yields exactly once
        """
