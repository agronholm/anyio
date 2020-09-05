import threading
from typing import Any, Callable, Coroutine, Dict, Optional, TypeVar, cast

from ..abc import BlockingPortal, CapacityLimiter
from ._eventloop import get_asynclib, run, threadlocals

T_Retval = TypeVar('T_Retval')


async def run_sync_in_worker_thread(
        func: Callable[..., T_Retval], *args, cancellable: bool = False,
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


def run_async_from_thread(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args) -> T_Retval:
    """
    Call a coroutine function from a worker thread.

    :param func: a coroutine function
    :param args: positional arguments for the callable
    :return: the return value of the coroutine function

    """
    try:
        asynclib = threadlocals.current_async_module
    except AttributeError:
        raise RuntimeError('This function can only be run from an AnyIO worker thread')

    return asynclib.run_async_from_thread(func, *args)


def current_default_worker_thread_limiter() -> CapacityLimiter:
    """
    Return the capacity limiter that is used by default to limit the number of concurrent threads.

    :return: a capacity limiter object

    """
    return get_asynclib().current_default_thread_limiter()


def create_blocking_portal() -> BlockingPortal:
    """
    Create a portal for running functions in the event loop thread from external threads.

    Use this function in asynchronous code when you need to allow external threads access to the
    event loop where your asynchronous code is currently running.
    """
    return get_asynclib().BlockingPortal()


def start_blocking_portal(
        backend: str = 'asyncio',
        backend_options: Optional[Dict[str, Any]] = None) -> BlockingPortal:
    """
    Start a new event loop in a new thread and run a blocking portal in its main task.

    The parameters are the same as for :func:`~anyio.run`.

    :param backend: name of the backend
    :param backend_options: backend options
    :return: a blocking portal object

    """
    async def run_portal():
        nonlocal portal
        async with create_blocking_portal() as portal:
            event.set()
            await portal.sleep_until_stopped()

    portal: Optional[BlockingPortal]
    event = threading.Event()
    kwargs = {'func': run_portal, 'backend': backend, 'backend_options': backend_options}
    thread = threading.Thread(target=run, kwargs=kwargs)
    thread.start()
    event.wait()
    return cast(BlockingPortal, portal)
