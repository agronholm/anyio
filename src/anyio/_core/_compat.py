from asyncio import iscoroutine
from contextlib import AbstractContextManager
from typing import (
    Any, AsyncContextManager, ContextManager, Coroutine, Optional, TypeVar, Union, cast, overload)

T = TypeVar('T')


@overload
async def maybe_async(__obj: Coroutine[Any, Any, T]) -> T:
    ...


@overload
async def maybe_async(__obj: T) -> T:
    ...


async def maybe_async(__obj):
    """
    Await on the given object if necessary.

    This function is intended to bridge the gap between AnyIO 2.x and 3.x where some functions and
    methods were converted from coroutine functions into regular functions.

    :return: the result of awaiting on the object if coroutine, or the object itself otherwise

    .. versionadded:: 2.2

    """
    if iscoroutine(__obj):
        return await __obj
    else:
        return __obj


class _ContextManagerWrapper:
    def __init__(self, cm: ContextManager[T]):
        self._cm = cm

    async def __aenter__(self) -> T:
        return self._cm.__enter__()

    async def __aexit__(self, exc_type, exc_val, exc_tb) -> Optional[bool]:
        return self._cm.__exit__(exc_type, exc_val, exc_tb)


def maybe_async_cm(cm: Union[ContextManager[T], AsyncContextManager[T]]) -> AsyncContextManager[T]:
    """
    Wrap a regular context manager as an async one if necessary.

    This function is intended to bridge the gap between AnyIO 2.x and 3.x where some functions and
    methods were changed to return regular context managers instead of async ones.

    :param cm: a regular or async context manager
    :return: an async context manager

    .. versionadded:: 2.2

    """
    if hasattr(cm, '__aenter__') and hasattr(cm, '__aexit__'):
        return cast(AsyncContextManager[T], cm)
    elif isinstance(cm, AbstractContextManager):
        return _ContextManagerWrapper(cm)

    raise TypeError('Given object is neither a regular or an asynchronous context manager')
