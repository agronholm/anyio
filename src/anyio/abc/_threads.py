import threading
from abc import ABCMeta, abstractmethod
from asyncio import iscoroutine
from concurrent.futures import Future
from contextlib import AbstractContextManager
from types import TracebackType
from typing import (
    Any, AsyncContextManager, Callable, ContextManager, Coroutine, Optional, Tuple, Type, TypeVar,
    cast, overload)

from .._core._synchronization import create_event
from .._core._tasks import open_cancel_scope
from ..abc import Event

T_Retval = TypeVar('T_Retval')
T_co = TypeVar('T_co', covariant=True)


class _BlockingAsyncContextManager(AbstractContextManager):
    _enter_future: Future
    _exit_future: Future
    _exit_event: Event
    _exit_exc_info: Tuple[Optional[Type[BaseException]], Optional[BaseException],
                          Optional[TracebackType]]

    def __init__(self, async_cm: AsyncContextManager[T_co], portal: 'BlockingPortal'):
        self._async_cm = async_cm
        self._portal = portal

    async def run_async_cm(self):
        try:
            self._exit_event = create_event()
            value = await self._async_cm.__aenter__()
        except BaseException as exc:
            self._enter_future.set_exception(exc)
            raise
        else:
            self._enter_future.set_result(value)

        await self._exit_event.wait()
        return await self._async_cm.__aexit__(*self._exit_exc_info)

    def __enter__(self) -> T_co:
        self._enter_future = Future()
        self._exit_future = self._portal.spawn_task(self.run_async_cm)
        cm = self._enter_future.result()
        return cast(T_co, cm)

    def __exit__(self, __exc_type: Optional[Type[BaseException]],
                 __exc_value: Optional[BaseException],
                 __traceback: Optional[TracebackType]) -> Optional[bool]:
        self._exit_exc_info = __exc_type, __exc_value, __traceback
        self._portal.call(self._exit_event.set)
        return self._exit_future.result()


class BlockingPortal(metaclass=ABCMeta):
    """An object tied that lets external threads run code in an asynchronous event loop."""

    __slots__ = '_task_group', '_event_loop_thread_id', '_stop_event', '_cancelled_exc_class'

    def __init__(self):
        from .. import create_event, create_task_group, get_cancelled_exc_class

        self._event_loop_thread_id = threading.get_ident()
        self._stop_event = create_event()
        self._task_group = create_task_group()
        self._cancelled_exc_class = get_cancelled_exc_class()

    async def __aenter__(self) -> 'BlockingPortal':
        await self._task_group.__aenter__()
        return self

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        await self.stop()
        return await self._task_group.__aexit__(exc_type, exc_val, exc_tb)

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_val, exc_tb):
        self.call(self.stop, exc_type is not None)

    async def sleep_until_stopped(self) -> None:
        """Sleep until :meth:`stop` is called."""
        await self._stop_event.wait()

    async def stop(self, cancel_remaining: bool = False) -> None:
        """
        Signal the portal to shut down.

        This marks the portal as no longer accepting new calls and exits from
        :meth:`sleep_until_stopped`.

        :param cancel_remaining: ``True`` to cancel all the remaining tasks, ``False`` to let them
            finish before returning

        """
        self._event_loop_thread_id = None
        await self._stop_event.set()
        if cancel_remaining:
            await self._task_group.cancel_scope.cancel()

    def stop_from_external_thread(self, cancel_remaining: bool = False) -> None:
        """
        Signal the portal to stop and wait for the event loop thread to finish.

        :param cancel_remaining: ``True`` to cancel all the remaining tasks, ``False`` to let them
            finish before returning

        """
        thread = self.call(threading.current_thread)
        self.call(self.stop, cancel_remaining)
        thread.join()

    async def _call_func(self, func: Callable, args: tuple, future: Future) -> None:
        def callback(f: Future):
            if f.cancelled():
                self.call(scope.cancel)

        try:
            retval = func(*args)
            if iscoroutine(retval):
                async with open_cancel_scope() as scope:
                    if future.cancelled():
                        await scope.cancel()
                    else:
                        future.add_done_callback(callback)

                    retval = await retval
        except self._cancelled_exc_class:
            future.cancel()
        except BaseException as exc:
            if not future.cancelled():
                future.set_exception(exc)

            # Let base exceptions fall through
            if not isinstance(exc, Exception):
                raise
        else:
            if not future.cancelled():
                future.set_result(retval)
        finally:
            scope = None

    @abstractmethod
    def _spawn_task_from_thread(self, func: Callable, args: tuple, future: Future) -> None:
        """
        Spawn a new task using the given callable.

        Implementors must ensure that the future is resolved when the task finishes.

        :param func: a callable
        :param args: positional arguments to be passed to the callable
        :param future: a future that will resolve to the return value of the callable, or the
            exception raised during its execution
        """

    @overload
    def call(self, func: Callable[..., Coroutine[Any, Any, T_Retval]], *args) -> T_Retval:
        ...

    @overload
    def call(self, func: Callable[..., T_Retval], *args) -> T_Retval:
        ...

    def call(self, func, *args):
        """
        Call the given function in the event loop thread.

        If the callable returns a coroutine object, it is awaited on.

        :param func: any callable
        :raises RuntimeError: if the portal is not running or if this method is called from within
            the event loop thread

        """
        return self.spawn_task(func, *args).result()

    def spawn_task(self, func: Callable[..., Coroutine], *args) -> Future:
        """
        Spawn a task in the portal's task group.

        The task will be run inside a cancel scope which can be cancelled by cancelling the
        returned future.

        :param func: the target coroutine function
        :param args: positional arguments passed to ``func``
        :return: a future that resolves with the return value of the callable if the task completes
            successfully, or with the exception raised in the task
        :raises RuntimeError: if the portal is not running or if this method is called from within
            the event loop thread

        .. versionadded:: 2.1

        """
        if self._event_loop_thread_id is None:
            raise RuntimeError('This portal is not running')
        if self._event_loop_thread_id == threading.get_ident():
            raise RuntimeError('This method cannot be called from the event loop thread')

        f: Future = Future()
        self._spawn_task_from_thread(func, args, f)
        return f

    def wrap_async_context_manager(self, cm: AsyncContextManager[T_co]) -> ContextManager[T_co]:
        """
        Wrap an async context manager as a synchronous context manager via this portal.

        Spawns a task that will call both ``__aenter__()`` and ``__aexit__()``, stopping in the
        middle until the synchronous context manager exits.

        :param cm: an asynchronous context manager
        :return: a synchronous context manager

        .. versionadded:: 2.1

        """
        return _BlockingAsyncContextManager(cm, self)
