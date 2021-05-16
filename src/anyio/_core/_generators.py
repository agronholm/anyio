import functools
import sys
from contextlib import asynccontextmanager

from ._exceptions import BrokenResourceError
from ._streams import create_memory_object_stream
from ._tasks import create_task_group


class _aclosing:
    def __init__(self, aiter):
        self._aiter = aiter

    async def __aenter__(self):
        return self._aiter

    async def __aexit__(self, *args):
        await self._aiter.aclose()


def wrapped_async_generator(wrapped):
    """async generator pattern which supports task groups and cancel scopes

    This decorator allows async generators to use a task group or cancel
    scope internally.  (Normally, it's not allowed to yield from these
    constructs within an async generator.)

    Though the wrapped function is written as a normal async generator, usage
    of the wrapper is different:  the wrapper is an async context manager
    providing the async generator to be iterated.

    Synopsis::

        >>> @wrapped_async_generator
        >>> async def my_generator():
        >>>    # yield values, possibly from a task group or cancel scope
        >>>    # ...
        >>>
        >>>
        >>> async with my_generator() as agen:
        >>>    async for value in agen:
        >>>        print(value)

    Implementation:  "The idea is that instead of pushing and popping the
    generator from the stack of the task that's consuming it, you instead run
    the generator code as a second task that feeds the consumer task values."
    See https://github.com/python-trio/trio/issues/638#issuecomment-431954073

    ISSUE: pylint is confused by this implementation, and every use will
      trigger not-async-context-manager
    """
    @asynccontextmanager
    @functools.wraps(wrapped)
    async def wrapper(*args, **kwargs):
        send_channel, receive_channel = create_memory_object_stream(0)
        async with create_task_group() as tg:
            async def adapter():
                async with send_channel, _aclosing(wrapped(*args, **kwargs)) as agen:
                    while True:
                        try:
                            # Advance underlying async generator to next yield
                            value = await agen.__anext__()
                        except StopAsyncIteration:
                            break
                        while True:
                            try:
                                # Forward the yielded value into the send channel
                                try:
                                    await send_channel.send(value)
                                except BrokenResourceError:
                                    return
                                break
                            except BaseException:  # pylint: disable=broad-except
                                # If send_channel.send() raised (e.g. Cancelled),
                                # throw the raised exception back into the generator,
                                # and get the next yielded value to forward.
                                try:
                                    value = await agen.athrow(*sys.exc_info())
                                except StopAsyncIteration:
                                    return

            tg.start_soon(adapter, name=wrapped)
            async with receive_channel:
                yield receive_channel
    return wrapper
