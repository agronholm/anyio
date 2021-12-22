import functools
import sys
from typing import Awaitable, Callable, Optional, TypeVar
from warnings import warn

if sys.version_info >= (3, 10):
    from typing import ParamSpec
else:
    from typing_extensions import ParamSpec

from ._core._eventloop import get_asynclib
from .abc import CapacityLimiter

T_Retval = TypeVar("T_Retval")
T_ParamSpec = ParamSpec("T_ParamSpec")


def asyncify(
    func: Callable[T_ParamSpec, T_Retval],
    *,
    cancellable: bool = False,
    limiter: Optional[CapacityLimiter] = None
) -> Callable[T_ParamSpec, Awaitable[T_Retval]]:
    """
    Take the given blocking function and create an async one that receives the same
    positional and keyword arguments, and that when called, calls the original function
    in a worker thread using ``to_thread.run_sync()``. Internally,
    ``to_thread.asyncify()`` uses the same ``to_thread.run_sync()``, but it supports
    keyword arguments additional to positional arguments and it adds better support for
    autocompletion and inline errors for the arguments of the function called.


    If the ``cancellable`` option is enabled and the task waiting for its completion is cancelled,
    the thread will still run its course but its return value (or any raised exception) will be
    ignored.

    Use it like this:

        def do_work(arg1, arg2, kwarg1="", kwarg2=""):
            # Do work

        result = await to_thread.asyncify(do_work)("spam", "ham", kwarg1="a", kwarg2="b")

    :param func: a callable
    :param cancellable: ``True`` to allow cancellation of the operation
    :param limiter: capacity limiter to use to limit the total amount of threads running
        (if omitted, the default limiter is used)
    :return: an async function that takes the same positional and keyword arguments
        as the original one, that when called runs the same original function in a
        thread worker and returns the result.

    """
    async def wrapper(*args: T_ParamSpec.args, **kwargs: T_ParamSpec.kwargs) -> T_Retval:
        partial_f = functools.partial(func, *args, **kwargs)
        return await run_sync(partial_f, cancellable=cancellable, limiter=limiter)
    return wrapper


async def run_sync(
        func: Callable[..., T_Retval], *args: object, cancellable: bool = False,
        limiter: Optional[CapacityLimiter] = None) -> T_Retval:
    """
    Call the given function with the given arguments in a worker thread.

    If the ``cancellable`` option is enabled and the task waiting for its completion is cancelled,
    the thread will still run its course but its return value (or any raised exception) will be
    ignored.

    :param func: a callable
    :param args: positional arguments for the callable
    :param cancellable: ``True`` to allow cancellation of the operation
    :param limiter: capacity limiter to use to limit the total amount of threads running
        (if omitted, the default limiter is used)
    :return: an awaitable that yields the return value of the function.

    """
    return await get_asynclib().run_sync_in_worker_thread(func, *args, cancellable=cancellable,
                                                          limiter=limiter)


async def run_sync_in_worker_thread(
        func: Callable[..., T_Retval], *args: object, cancellable: bool = False,
        limiter: Optional[CapacityLimiter] = None) -> T_Retval:
    warn('run_sync_in_worker_thread() has been deprecated, use anyio.to_thread.run_sync() instead',
         DeprecationWarning)
    return await run_sync(func, *args, cancellable=cancellable, limiter=limiter)


def current_default_thread_limiter() -> CapacityLimiter:
    """
    Return the capacity limiter that is used by default to limit the number of concurrent threads.

    :return: a capacity limiter object

    """
    return get_asynclib().current_default_thread_limiter()


def current_default_worker_thread_limiter() -> CapacityLimiter:
    warn('current_default_worker_thread_limiter() has been deprecated, '
         'use anyio.to_thread.current_default_thread_limiter() instead',
         DeprecationWarning)
    return current_default_thread_limiter()
