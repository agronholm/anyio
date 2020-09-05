import threading
from abc import ABCMeta, abstractmethod
from concurrent.futures import Future
from typing import Any, Callable, Coroutine, TypeVar, overload

T_Retval = TypeVar('T_Retval')


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
        try:
            retval = func(*args)
            if isinstance(retval, Coroutine):
                future.set_result(await retval)
            else:
                future.set_result(retval)
        except self._cancelled_exc_class:
            future.cancel()
        except BaseException as exc:
            future.set_exception(exc)

    @abstractmethod
    def _spawn_task_from_thread(self, func: Callable, args: tuple, future: Future) -> None:
        pass

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

        :raises RuntimeError: if this method is called from within the event loop thread

        """
        if self._event_loop_thread_id is None:
            raise RuntimeError('This portal is not running')
        if self._event_loop_thread_id == threading.get_ident():
            raise RuntimeError('This method cannot be called from the event loop thread')

        future: Future = Future()
        self._spawn_task_from_thread(func, args, future)
        return future.result()
