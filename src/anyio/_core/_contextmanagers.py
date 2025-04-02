from __future__ import annotations

from abc import abstractmethod
from collections.abc import AsyncGenerator, Generator
from inspect import isasyncgen, iscoroutine
from types import TracebackType
from typing import Generic, TypeVar, final

T = TypeVar("T")


class ContextManagerMixin(Generic[T]):
    """
    Mixin class providing context manager functionality via a generator-based
    implementation.

    This class allows you to implement a context manager using a generator, similar to
    :func:`contextlib.contextmanager`, but for classes that need to embed other context
    managers.

    This class is designed to streamline the use of context management by
    requiring the implementation of the `__contextmanager__` method, which
    should yield instances of the class itself. It then wraps this generator
    with the standard `__enter__` and `__exit__` methods to make the class
    work seamlessly in `with` statements.

    The mixin enforces type checking to ensure consistency and correctness,
    validating that the yielded value from the generator is an instance of the
    class itself.
    """

    @final
    def __enter__(self) -> T:
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
    def __contextmanager__(self) -> Generator[T, None, None]:
        pass


class AsyncContextManagerMixin(Generic[T]):
    @final
    async def __aenter__(self) -> T:
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
    def __asynccontextmanager__(self) -> AsyncGenerator[T, None]:
        pass
