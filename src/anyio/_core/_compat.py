from abc import ABCMeta, abstractmethod
from contextlib import AbstractContextManager
from types import TracebackType
from typing import (
    TYPE_CHECKING, AsyncContextManager, Callable, ContextManager, Generic, Iterable, List,
    Optional, Tuple, Type, TypeVar, Union, overload)
from warnings import warn

if TYPE_CHECKING:
    from ._testing import TaskInfo
else:
    TaskInfo = object

T = TypeVar('T')
AnyDeprecatedAwaitable = Union['DeprecatedAwaitable', 'DeprecatedAwaitableFloat',
                               'DeprecatedAwaitableList', TaskInfo]


@overload
async def maybe_async(__obj: TaskInfo) -> TaskInfo:
    ...


@overload
async def maybe_async(__obj: 'DeprecatedAwaitableFloat') -> float:
    ...


@overload
async def maybe_async(__obj: 'DeprecatedAwaitableList[T]') -> List[T]:
    ...


@overload
async def maybe_async(__obj: 'DeprecatedAwaitable') -> None:
    ...


async def maybe_async(__obj: AnyDeprecatedAwaitable) -> Union[TaskInfo, float, list, None]:
    """
    Await on the given object if necessary.

    This function is intended to bridge the gap between AnyIO 2.x and 3.x where some functions and
    methods were converted from coroutine functions into regular functions.

    Do **not** try to use this for any other purpose!

    :return: the result of awaiting on the object if coroutine, or the object itself otherwise

    .. versionadded:: 2.2

    """
    return __obj._unwrap()


class _ContextManagerWrapper:
    def __init__(self, cm: ContextManager[T]):
        self._cm = cm

    async def __aenter__(self) -> T:
        return self._cm.__enter__()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
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
    if not isinstance(cm, AbstractContextManager):
        raise TypeError('Given object is not an context manager')

    return _ContextManagerWrapper(cm)


def _warn_deprecation(awaitable: AnyDeprecatedAwaitable, stacklevel: int = 1) -> None:
    warn(f'Awaiting on {awaitable._name}() is deprecated. Use "await '
         f'anyio.maybe_async({awaitable._name}(...)) if you have to support both AnyIO 2.x '
         f'and 3.x, or just remove the "await" if you are completely migrating to AnyIO 3+.',
         DeprecationWarning, stacklevel=stacklevel + 1)


class DeprecatedAwaitable:
    def __init__(self, func: Callable[..., 'DeprecatedAwaitable']):
        self._name = f'{func.__module__}.{func.__qualname__}'

    def __await__(self) -> Iterable[None]:
        _warn_deprecation(self)
        if False:
            yield

    def __reduce__(self) -> Tuple[Type[None], Tuple]:
        return type(None), ()

    def _unwrap(self) -> None:
        return None


class DeprecatedAwaitableFloat(float):
    def __new__(
        cls, x: float, func: Callable[..., 'DeprecatedAwaitableFloat']
    ) -> 'DeprecatedAwaitableFloat':
        return super().__new__(cls, x)

    def __init__(self, x: float, func: Callable[..., 'DeprecatedAwaitableFloat']):
        self._name = f'{func.__module__}.{func.__qualname__}'

    def __await__(self) -> Iterable[float]:
        _warn_deprecation(self)
        if False:
            yield

        return float(self)

    def __reduce__(self) -> Tuple[Type[float], Tuple[float]]:
        return float, (float(self),)

    def _unwrap(self) -> float:
        return float(self)


class DeprecatedAwaitableList(List[T]):
    def __init__(self, *args: T, func: Callable[..., 'DeprecatedAwaitableList']):
        super().__init__(*args)
        self._name = f'{func.__module__}.{func.__qualname__}'

    def __await__(self) -> Iterable[List[T]]:
        _warn_deprecation(self)
        if False:
            yield

        return list(self)

    def __reduce__(self) -> Tuple[Type[list], Tuple[List[T]]]:
        return list, (list(self),)

    def _unwrap(self) -> List[T]:
        return list(self)


class DeprecatedAsyncContextManager(Generic[T], metaclass=ABCMeta):
    @abstractmethod
    def __enter__(self) -> T:
        pass

    @abstractmethod
    def __exit__(self, exc_type: Optional[Type[BaseException]],
                 exc_val: Optional[BaseException],
                 exc_tb: Optional[TracebackType]) -> Optional[bool]:
        pass

    async def __aenter__(self) -> T:
        warn(f'Using {self.__class__.__name__} as an async context manager has been deprecated. '
             f'Use "async with anyio.maybe_async_cm(yourcontextmanager) as foo:" if you have to '
             f'support both AnyIO 2.x and 3.x, or just remove the "async" from "async with" if '
             f'you are completely migrating to AnyIO 3+.', DeprecationWarning)
        return self.__enter__()

    async def __aexit__(self, exc_type: Optional[Type[BaseException]],
                        exc_val: Optional[BaseException],
                        exc_tb: Optional[TracebackType]) -> Optional[bool]:
        return self.__exit__(exc_type, exc_val, exc_tb)
