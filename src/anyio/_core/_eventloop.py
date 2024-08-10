from __future__ import annotations

import math
import os
import sys
import threading
from collections.abc import Awaitable, Callable, Generator
from contextlib import contextmanager
from importlib import import_module
from typing import TYPE_CHECKING, Any, TypeVar

import sniffio

if sys.version_info >= (3, 11):
    from typing import TypeVarTuple, Unpack
else:
    from typing_extensions import TypeVarTuple, Unpack

if TYPE_CHECKING:
    from ..abc import AsyncBackend

# This must be updated when new backends are introduced
BACKENDS = "asyncio", "trio"

T_Retval = TypeVar("T_Retval")
PosArgsT = TypeVarTuple("PosArgsT")

threadlocals = threading.local()
loaded_backends: dict[str, type[AsyncBackend]] = {}
forced_backend_name = os.getenv("ANYIO_BACKEND")
forced_backend: type[AsyncBackend] | None = None


def run(
    func: Callable[[Unpack[PosArgsT]], Awaitable[T_Retval]],
    *args: Unpack[PosArgsT],
    backend: str | None = None,
    backend_options: dict[str, Any] | None = None,
) -> T_Retval:
    """
    Run the given coroutine function in an asynchronous event loop.

    The current thread must not be already running an event loop.

    The backend will be chosen using the following priority list:
    * the ``backend`` argument, if not ``None``
    * the ``ANYIO_BACKEND`` environment variable
    * ``asyncio``

    :param func: a coroutine function
    :param args: positional arguments to ``func``
    :param backend: name of the asynchronous event loop implementation – currently
        either ``asyncio`` or ``trio``
    :param backend_options: keyword arguments to call the backend ``run()``
        implementation with (documented :ref:`here <backend options>`)
    :return: the return value of the coroutine function
    :raises RuntimeError: if an asynchronous event loop is already running in this
        thread
    :raises LookupError: if the named backend is not found

    """
    try:
        asynclib_name = sniffio.current_async_library()
    except sniffio.AsyncLibraryNotFoundError:
        pass
    else:
        raise RuntimeError(f"Already running {asynclib_name} in this thread")

    backend = backend or os.getenv("ANYIO_BACKEND") or "asyncio"
    try:
        async_backend = get_async_backend(backend)
    except ImportError as exc:
        raise LookupError(f"No such backend: {backend}") from exc

    token = None
    if sniffio.current_async_library_cvar.get(None) is None:
        # Since we're in control of the event loop, we can cache the name of the async
        # library
        token = sniffio.current_async_library_cvar.set(backend)

    try:
        backend_options = backend_options or {}
        return async_backend.run(func, args, {}, backend_options)
    finally:
        if token:
            sniffio.current_async_library_cvar.reset(token)


async def sleep(delay: float) -> None:
    """
    Pause the current task for the specified duration.

    :param delay: the duration, in seconds

    """
    return await get_async_backend().sleep(delay)


async def sleep_forever() -> None:
    """
    Pause the current task until it's cancelled.

    This is a shortcut for ``sleep(math.inf)``.

    .. versionadded:: 3.1

    """
    await sleep(math.inf)


async def sleep_until(deadline: float) -> None:
    """
    Pause the current task until the given time.

    :param deadline: the absolute time to wake up at (according to the internal
        monotonic clock of the event loop)

    .. versionadded:: 3.1

    """
    now = current_time()
    await sleep(max(deadline - now, 0))


def current_time() -> float:
    """
    Return the current value of the event loop's internal clock.

    :return: the clock value (seconds)

    """
    return get_async_backend().current_time()


def get_all_backends() -> tuple[str, ...]:
    """
    Return a tuple of the names of all built-in backends.

    If the ``ANYIO_BACKEND`` environment variable was set, then the returned tuple will
    only contain that backend.

    """
    if forced_backend_name:
        return (forced_backend_name,)

    return BACKENDS


def get_cancelled_exc_class() -> type[BaseException]:
    """Return the current async library's cancellation exception class."""
    return get_async_backend().cancelled_exception_class()


#
# Private API
#


@contextmanager
def claim_worker_thread(
    backend_class: type[AsyncBackend], token: object
) -> Generator[Any, None, None]:
    threadlocals.current_async_backend = backend_class
    threadlocals.current_token = token
    try:
        yield
    finally:
        del threadlocals.current_async_backend
        del threadlocals.current_token


def get_async_backend(asynclib_name: str | None = None) -> type[AsyncBackend]:
    global forced_backend

    if forced_backend is not None:
        return forced_backend

    # We use our own dict instead of sys.modules to get the already imported back-end
    # class because the appropriate modules in sys.modules could potentially be only
    # partially initialized
    asynclib_name = (
        asynclib_name or forced_backend_name or sniffio.current_async_library()
    )
    try:
        return loaded_backends[asynclib_name]
    except KeyError:
        module = import_module(f"anyio._backends._{asynclib_name}")
        loaded_backends[asynclib_name] = module.backend_class
        if asynclib_name == forced_backend_name:
            forced_backend = module.backend_class

        return module.backend_class
