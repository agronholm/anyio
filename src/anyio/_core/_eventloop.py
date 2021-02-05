import sys
import threading
from contextlib import contextmanager
from importlib import import_module
from typing import Any, Callable, Coroutine, Dict, Generator, Optional, Tuple, Type, TypeVar

import sniffio

# This must be updated when new backends are introduced
BACKENDS = 'asyncio', 'curio', 'trio'

T_Retval = TypeVar('T_Retval', covariant=True)
threadlocals = threading.local()


def run(func: Callable[..., Coroutine[Any, Any, T_Retval]], *args,
        backend: str = 'asyncio', backend_options: Optional[Dict[str, Any]] = None) -> T_Retval:
    """
    Run the given coroutine function in an asynchronous event loop.

    The current thread must not be already running an event loop.

    :param func: a coroutine function
    :param args: positional arguments to ``func``
    :param backend: name of the asynchronous event loop implementation – one of ``asyncio``,
        ``curio`` and ``trio``
    :param backend_options: keyword arguments to call the backend ``run()`` implementation with
        (documented :ref:`here <backend options>`)
    :return: the return value of the coroutine function
    :raises RuntimeError: if an asynchronous event loop is already running in this thread
    :raises LookupError: if the named backend is not found

    """
    try:
        asynclib_name = sniffio.current_async_library()
    except sniffio.AsyncLibraryNotFoundError:
        pass
    else:
        raise RuntimeError(f'Already running {asynclib_name} in this thread')

    try:
        asynclib = import_module(f'..._backends._{backend}', package=__name__)
    except ImportError as exc:
        raise LookupError(f'No such backend: {backend}') from exc

    token = None
    if sniffio.current_async_library_cvar.get(None) is None:
        # Since we're in control of the event loop, we can cache the name of the async library
        token = sniffio.current_async_library_cvar.set(backend)

    try:
        backend_options = backend_options or {}
        return asynclib.run(func, *args, **backend_options)  # type: ignore
    finally:
        if token:
            sniffio.current_async_library_cvar.reset(token)


async def sleep(delay: float) -> None:
    """
    Pause the current task for the specified duration.

    :param delay: the duration, in seconds

    """
    return await get_asynclib().sleep(delay)


async def current_time() -> float:
    """
    Return the current value of the event loop's internal clock.

    :return: the clock value (seconds)

    """
    return await get_asynclib().current_time()


def get_all_backends() -> Tuple[str, ...]:
    """Return a tuple of the names of all built-in backends."""
    return BACKENDS


def get_cancelled_exc_class() -> Type[BaseException]:
    """Return the current async library's cancellation exception class."""
    return get_asynclib().CancelledError


#
# Private API
#

@contextmanager
def claim_worker_thread(backend) -> Generator[Any, None, None]:
    module = sys.modules['anyio._backends._' + backend]
    threadlocals.current_async_module = module
    token = sniffio.current_async_library_cvar.set(backend)
    try:
        yield
    finally:
        sniffio.current_async_library_cvar.reset(token)
        del threadlocals.current_async_module


def get_asynclib(asynclib_name: Optional[str] = None):
    if asynclib_name is None:
        asynclib_name = sniffio.current_async_library()

    modulename = 'anyio._backends._' + asynclib_name
    try:
        return sys.modules[modulename]
    except KeyError:
        return import_module(modulename)
