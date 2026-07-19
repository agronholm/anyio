"""
A standalone copy of :class:`asyncio.Runner` (added in Python 3.11), backported for
Python 3.10. On 3.11+ this simply re-exports the stdlib implementation.
"""

from __future__ import annotations

import sys

if sys.version_info >= (3, 11):
    from asyncio import Runner as Runner
else:
    import asyncio
    import contextvars
    import enum
    import signal
    import threading
    from asyncio import AbstractEventLoop, coroutines, events, exceptions, tasks
    from collections.abc import Callable, Coroutine
    from functools import partial
    from types import TracebackType
    from typing import TypeVar

    T_Retval = TypeVar("T_Retval")

    class _State(enum.Enum):
        CREATED = "created"
        INITIALIZED = "initialized"
        CLOSED = "closed"

    class Runner:
        # Copied from CPython 3.11
        def __init__(
            self,
            *,
            debug: bool | None = None,
            loop_factory: Callable[[], AbstractEventLoop] | None = None,
        ):
            self._state = _State.CREATED
            self._debug = debug
            self._loop_factory = loop_factory
            self._loop: AbstractEventLoop | None = None
            self._context = None
            self._interrupt_count = 0
            self._set_event_loop = False

        def __enter__(self) -> Runner:
            self._lazy_init()
            return self

        def __exit__(
            self,
            exc_type: type[BaseException] | None,
            exc_val: BaseException | None,
            exc_tb: TracebackType | None,
        ) -> None:
            self.close()

        def close(self) -> None:
            """Shutdown and close event loop."""
            loop = self._loop
            if self._state is not _State.INITIALIZED or loop is None:
                return
            try:
                _cancel_all_tasks(loop)
                loop.run_until_complete(loop.shutdown_asyncgens())
                if hasattr(loop, "shutdown_default_executor"):
                    loop.run_until_complete(loop.shutdown_default_executor())
                else:
                    loop.run_until_complete(_shutdown_default_executor(loop))
            finally:
                if self._set_event_loop:
                    events.set_event_loop(None)
                loop.close()
                self._loop = None
                self._state = _State.CLOSED

        def get_loop(self) -> AbstractEventLoop:
            """Return embedded event loop."""
            self._lazy_init()
            return self._loop

        def run(self, coro: Coroutine[T_Retval], *, context=None) -> T_Retval:
            """Run a coroutine inside the embedded event loop."""
            if not coroutines.iscoroutine(coro):
                raise ValueError(f"a coroutine was expected, got {coro!r}")

            if events._get_running_loop() is not None:
                # fail fast with short traceback
                raise RuntimeError(
                    "Runner.run() cannot be called from a running event loop"
                )

            self._lazy_init()

            if context is None:
                context = self._context
            task = context.run(self._loop.create_task, coro)

            if (
                threading.current_thread() is threading.main_thread()
                and signal.getsignal(signal.SIGINT) is signal.default_int_handler
            ):
                sigint_handler = partial(self._on_sigint, main_task=task)
                try:
                    signal.signal(signal.SIGINT, sigint_handler)
                except ValueError:
                    # `signal.signal` may throw if `threading.main_thread` does
                    # not support signals (e.g. embedded interpreter with signals
                    # not registered - see gh-91880)
                    sigint_handler = None
            else:
                sigint_handler = None

            self._interrupt_count = 0
            try:
                return self._loop.run_until_complete(task)
            except exceptions.CancelledError:
                if self._interrupt_count > 0:
                    uncancel = getattr(task, "uncancel", None)
                    if uncancel is not None and uncancel() == 0:
                        raise KeyboardInterrupt  # noqa: B904
                raise  # CancelledError
            finally:
                if (
                    sigint_handler is not None
                    and signal.getsignal(signal.SIGINT) is sigint_handler
                ):
                    signal.signal(signal.SIGINT, signal.default_int_handler)

        def _lazy_init(self) -> None:
            if self._state is _State.CLOSED:
                raise RuntimeError("Runner is closed")
            if self._state is _State.INITIALIZED:
                return
            if self._loop_factory is None:
                self._loop = events.new_event_loop()
                if not self._set_event_loop:
                    # Call set_event_loop only once to avoid calling
                    # attach_loop multiple times on child watchers
                    events.set_event_loop(self._loop)
                    self._set_event_loop = True
            else:
                self._loop = self._loop_factory()
            if self._debug is not None:
                self._loop.set_debug(self._debug)
            self._context = contextvars.copy_context()
            self._state = _State.INITIALIZED

        def _on_sigint(self, signum, frame, main_task: asyncio.Task) -> None:
            self._interrupt_count += 1
            if self._interrupt_count == 1 and not main_task.done():
                main_task.cancel()
                # wakeup loop if it is blocked by select() with long timeout
                self._loop.call_soon_threadsafe(lambda: None)
                return
            raise KeyboardInterrupt()

    def _cancel_all_tasks(loop: AbstractEventLoop) -> None:
        to_cancel = tasks.all_tasks(loop)
        if not to_cancel:
            return

        for task in to_cancel:
            task.cancel()

        loop.run_until_complete(tasks.gather(*to_cancel, return_exceptions=True))

        for task in to_cancel:
            if task.cancelled():
                continue
            if task.exception() is not None:
                loop.call_exception_handler(
                    {
                        "message": "unhandled exception during asyncio.run() shutdown",
                        "exception": task.exception(),
                        "task": task,
                    }
                )

    async def _shutdown_default_executor(loop: AbstractEventLoop) -> None:
        """Schedule the shutdown of the default executor."""

        def _do_shutdown(future: asyncio.futures.Future) -> None:
            try:
                loop._default_executor.shutdown(wait=True)  # type: ignore[attr-defined]
                loop.call_soon_threadsafe(future.set_result, None)
            except Exception as ex:
                loop.call_soon_threadsafe(future.set_exception, ex)

        loop._executor_shutdown_called = True
        if loop._default_executor is None:
            return
        future = loop.create_future()
        thread = threading.Thread(target=_do_shutdown, args=(future,))
        thread.start()
        try:
            await future
        finally:
            thread.join()
