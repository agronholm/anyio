"""
These utility functions exist to support anyio pytest plugin's context management

Do *not* use them outside of it, for the following reasons:

 * context_wrap/context_wrap_async are expected to be used only on respectively
   synchronous/asynchronous fixture and test functions, and they are not robust
   in the face of unusual ways in which such functions can theoretically be written;
 * The wrapping of coroutines by context_wrap_async is likely to have a noticeable
   overhead compared to the way that asyncio and trio integrate Context objects in
   their library APIs;
"""

from __future__ import annotations

from collections.abc import AsyncGenerator, Awaitable, Generator
from functools import wraps
from inspect import isasyncgenfunction, isgeneratorfunction
from typing import Protocol


class ContextLike(Protocol):
    def run(self, func, /, *args, **kwargs):
        raise NotImplementedError


class GeneratorWrapper(Generator):
    def __init__(self, context, wrapped):
        self._context = context
        self._wrapped = wrapped

    def send(self, value, /):
        return self._context.run(self._wrapped.send, value)

    def throw(self, typ, val=None, tb=None, /):
        return self._context.run(self._wrapped.throw, typ, val, tb)


class AwaitableWrapper(Awaitable):
    def __init__(self, context, wrapped):
        self._context = context
        self._wrapped = wrapped

    def __await__(self):
        generator = self._context.run(self._wrapped.__await__)
        return GeneratorWrapper(self._context, generator)


class AsyncGeneratorWrapper(AsyncGenerator):
    def __init__(self, context, wrapped):
        self._context = context
        self._wrapped = wrapped

    def asend(self, value, /):
        awaitable = self._context.run(self._wrapped.asend, value)
        return AwaitableWrapper(self._context, awaitable)

    def athrow(self, typ, val=None, tb=None, /):
        awaitable = self._context.run(self._wrapped.athrow, typ, val, tb)
        return AwaitableWrapper(self._context, awaitable)


def context_wrap(context, func, /):
    if isgeneratorfunction(func):

        @wraps(func)
        def generator_wrapper(*args, **kwargs):
            generator = context.run(func, *args, **kwargs)
            result = yield from GeneratorWrapper(context, generator)
            return result

        return generator_wrapper

    else:

        @wraps(func)
        def func_wrapper(*args, **kwargs):
            result = context.run(func, *args, **kwargs)
            return result

        return func_wrapper


def context_wrap_async(context, func, /):
    if isasyncgenfunction(func):

        @wraps(func)
        def asyncgen_wrapper(*args, **kwargs):
            asyncgen = context.run(func, *args, **kwargs)
            return AsyncGeneratorWrapper(context, asyncgen)

        return asyncgen_wrapper

    else:

        @wraps(func)
        async def coroutine_wrapper(*args, **kwargs):
            coro = context.run(func, *args, **kwargs)
            result = await AwaitableWrapper(context, coro)
            return result

        return coroutine_wrapper
