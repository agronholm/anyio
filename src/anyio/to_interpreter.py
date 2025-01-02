from __future__ import annotations

import atexit
import os
import pickle
import sys
from collections import deque
from collections.abc import Callable, Mapping
from textwrap import dedent
from typing import Any, TypeVar

from . import to_thread
from ._core._exceptions import BrokenWorkerIntepreter
from ._core._synchronization import CapacityLimiter
from .lowlevel import RunVar

if sys.version_info >= (3, 11):
    from typing import TypeVarTuple, Unpack
else:
    from typing_extensions import TypeVarTuple, Unpack

UNBOUND = 2  # I have no clue how this works, but it was used in the stdlib
FMT_UNPICKLED = 0
FMT_PICKLED = 1
DEFAULT_CPU_COUNT = 8  # this is just an arbitrarily selected value

T_Retval = TypeVar("T_Retval")
PosArgsT = TypeVarTuple("PosArgsT")

_idle_workers = RunVar[deque["Worker"]]("_available_workers")
_default_interpreter_limiter = RunVar[CapacityLimiter]("_default_interpreter_limiter")


class Worker:
    _run_func = compile(
        dedent("""
        import _interpqueues as queues
        import _interpreters as interpreters
        from pickle import loads, dumps, HIGHEST_PROTOCOL

        item = queues.get(queue_id)[0]
        try:
            func, args, kwargs = loads(item)
            retval = func(*args, **kwargs)
        except Exception as exc:
            is_exception = True
            retval = exc
        else:
            is_exception = False

        try:
            queues.put(queue_id, (retval, is_exception), FMT_UNPICKLED, UNBOUND)
        except interpreters.NotShareableError:
            retval = dumps(retval, HIGHEST_PROTOCOL)
            queues.put(queue_id, (retval, is_exception), FMT_PICKLED, UNBOUND)
        """),
        "<string>",
        "exec",
    )

    _initialized: bool = False
    _interpreter_id: int
    _queue_id: int

    def initialize(self) -> None:
        import _interpqueues as queues
        import _interpreters as interpreters

        self._interpreter_id = interpreters.create()
        self._queue_id = queues.create(2, FMT_UNPICKLED, UNBOUND)  # type: ignore[call-arg]
        self._initialized = True
        interpreters.set___main___attrs(
            self._interpreter_id,
            {
                "queue_id": self._queue_id,
                "FMT_PICKLED": FMT_PICKLED,
                "FMT_UNPICKLED": FMT_UNPICKLED,
                "UNBOUND": UNBOUND,
            },
        )

    def destroy(self) -> None:
        import _interpqueues as queues
        import _interpreters as interpreters

        if self._initialized:
            interpreters.destroy(self._interpreter_id)
            queues.destroy(self._queue_id)

    def _call(
        self, func: Callable[..., T_Retval], args: tuple[Any], kwargs: dict[str, Any]
    ) -> tuple[Any, bool]:
        import _interpqueues as queues
        import _interpreters as interpreters

        if not self._initialized:
            self.initialize()

        payload = pickle.dumps((func, args, kwargs), pickle.HIGHEST_PROTOCOL)
        queues.put(self._queue_id, payload, FMT_PICKLED, UNBOUND)  # type: ignore[call-arg]

        res: Any
        is_exception: bool
        if exc_info := interpreters.exec(self._interpreter_id, self._run_func):  # type: ignore[func-returns-value,arg-type]
            raise BrokenWorkerIntepreter(exc_info)

        (res, is_exception), fmt = queues.get(self._queue_id)[:2]
        if fmt == FMT_PICKLED:
            res = pickle.loads(res)

        return res, is_exception

    async def call(
        self,
        func: Callable[..., T_Retval],
        args: tuple[Any],
        kwargs: dict[str, Any],
        abandon_on_cancel: bool,
        limiter: CapacityLimiter,
    ) -> T_Retval:
        result, is_exception = await to_thread.run_sync(
            self._call,
            func,
            args,
            kwargs,
            abandon_on_cancel=abandon_on_cancel,
            limiter=limiter,
        )
        if is_exception:
            raise result

        return result


def _stop_workers(workers: deque[Worker]) -> None:
    for worker in workers:
        worker.destroy()

    workers.clear()


async def run_sync(
    func: Callable[[Unpack[PosArgsT]], T_Retval],
    *args: Unpack[PosArgsT],
    kwargs: Mapping[str, Any] | None = None,
    abandon_on_cancel: bool = False,
    limiter: CapacityLimiter | None = None,
) -> T_Retval:
    """
    Call the given function with the given arguments in a subinterpreter.

    If the ``cancellable`` option is enabled and the task waiting for its completion is
    cancelled, the call will still run its course but its return value (or any raised
    exception) will be ignored.

    .. warning:: This feature is **experimental**. The upstream interpreter API has not
        yet been finalized or thoroughly tested, so don't rely on this for anything
        mission critical.

    :param func: a callable
    :param args: positional arguments for the callable
    :param kwargs: keyword arguments for the callable
    :param abandon_on_cancel: ``True`` to abandon the call (leaving it to run
        unchecked on its own) if the host task is cancelled, ``False`` to ignore
        cancellations in the host task until the operation has completed in the
        subinterpreter
    :param limiter: capacity limiter to use to limit the total amount of subinterpreters
        running (if omitted, the default limiter is used)
    :return: the result of the call
    :raises BrokenWorkerIntepreter: if there's an internal error in a subinterpreter

    """
    if sys.version_info <= (3, 13):
        raise RuntimeError("subinterpreters require at least Python 3.13")

    if limiter is None:
        limiter = current_default_interpreter_limiter()

    try:
        idle_workers = _idle_workers.get()
    except LookupError:
        idle_workers = deque()
        _idle_workers.set(idle_workers)
        atexit.register(_stop_workers, idle_workers)

    async with limiter:
        try:
            worker = idle_workers.pop()
        except IndexError:
            worker = Worker()

    try:
        return await worker.call(func, args, kwargs or {}, abandon_on_cancel, limiter)
    finally:
        idle_workers.append(worker)


def current_default_interpreter_limiter() -> CapacityLimiter:
    """
    Return the capacity limiter that is used by default to limit the number of
    concurrently running subinterpreters.

    Defaults to the number of CPU cores.

    :return: a capacity limiter object

    """
    try:
        return _default_interpreter_limiter.get()
    except LookupError:
        limiter = CapacityLimiter(os.cpu_count() or DEFAULT_CPU_COUNT)
        _default_interpreter_limiter.set(limiter)
        return limiter
