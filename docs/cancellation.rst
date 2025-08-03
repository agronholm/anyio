Cancellation and timeouts
=========================

.. py:currentmodule:: anyio

The ability to cancel tasks is the foremost advantage of the asynchronous programming
model. Threads, on the other hand, cannot be forcibly killed and shutting them down will
require perfect cooperation from the code running in them.

Cancellation in AnyIO follows the model established by the Trio_ framework. This means
that cancellation of tasks is done via so called *cancel scopes*. Cancel scopes are used
as context managers and can be nested. Cancelling a cancel scope cancels all cancel
scopes nested within it. If a task is waiting on something, it is cancelled immediately.
If the task is just starting, it will run until it first tries to run an operation
requiring waiting, such as :func:`~sleep`.

A task group contains its own cancel scope. The entire task group can be cancelled by
cancelling this scope::

    from anyio import create_task_group, get_cancelled_exc_class, sleep, run


    async def waiter(index: int):
        try:
            await sleep(1)
        except get_cancelled_exc_class():
            print(f"Waiter {index} cancelled")
            raise


    async def taskfunc():
        async with create_task_group() as tg:
            # Start a couple tasks and wait until they are blocked
            tg.start_soon(waiter, 1)
            tg.start_soon(waiter, 2)
            await sleep(0.1)

            # Cancel the scope and exit the task group
            tg.cancel_scope.cancel()

    run(taskfunc)

    # Output:
    # Waiter 1 cancelled
    # Waiter 2 cancelled

.. _Trio: https://trio.readthedocs.io/en/latest/reference-core.html
   #cancellation-and-timeouts

.. _asyncio cancellation:

Differences between asyncio and AnyIO cancellation semantics
------------------------------------------------------------

Asyncio employs a type of cancellation called *edge cancellation*. This means that when
a task is cancelled, a :exc:`~asyncio.CancelledError` is raised in the task and the task
then gets to handle it however it likes, even opting to ignore it entirely. In contrast,
tasks that either explicitly use a cancel scope, or are spawned from an AnyIO task
group, use *level cancellation*. This means that as long as a task remains within an
*effectively cancelled* cancel scope, it will get hit with a cancellation exception any
time it hits a *yield point* (usually by awaiting something, or through
``async with ...`` or ``async for ...``).

This can cause difficulties when running code written for asyncio that does not expect
to get cancelled repeatedly. For example, :class:`asyncio.Condition` was written in such
a way that it suppresses cancellation exceptions until it is able to reacquire the
underlying lock. This can lead to a busy-wait_ loop that needlessly consumes a lot of
CPU time.

.. _busy-wait: https://en.wikipedia.org/wiki/Busy_waiting

Timeouts
--------

Networked operations can often take a long time, and you usually want to set up some
kind of a timeout to ensure that your application doesn't stall forever. There are two
principal ways to do this: :func:`~move_on_after` and :func:`~fail_after`. Both are used
as synchronous context managers. The difference between these two is that the former
simply exits the context block prematurely on a timeout, while the other raises a
:exc:`TimeoutError`.

Both methods create a new cancel scope, and you can check the deadline by accessing the
:attr:`~.CancelScope.deadline` attribute. Note, however, that an outer cancel scope
may have an earlier deadline than your current cancel scope. To check the actual
deadline, you can use the :func:`~current_effective_deadline` function.

Here's how you typically use timeouts::

    from anyio import create_task_group, move_on_after, sleep, run


    async def main():
        async with create_task_group() as tg:
            with move_on_after(1) as scope:
                print('Starting sleep')
                await sleep(2)
                print('This should never be printed')

            # The cancelled_caught property will be True if timeout was reached
            print('Exited cancel scope, cancelled =', scope.cancelled_caught)

    run(main)

.. note:: It's recommended not to directly cancel a scope from :func:`~fail_after`, as
    that may currently result in :exc:`TimeoutError` being erroneously raised if exiting
    the scope is delayed long enough for the deadline to be exceeded.

Shielding
---------

There are cases where you want to shield your task from cancellation, at least
temporarily. The most important such use case is performing shutdown procedures on
asynchronous resources.

To accomplish this, open a new cancel scope with the ``shield=True`` argument::

    from anyio import CancelScope, create_task_group, sleep, run


    async def external_task():
        print('Started sleeping in the external task')
        await sleep(1)
        print('This line should never be seen')


    async def main():
        async with create_task_group() as tg:
            with CancelScope(shield=True) as scope:
                tg.start_soon(external_task)
                tg.cancel_scope.cancel()
                print('Started sleeping in the host task')
                await sleep(1)
                print('Finished sleeping in the host task')

    run(main)

The shielded block will be exempt from cancellation except when the shielded block
itself is being cancelled. Shielding a cancel scope is often best combined with
:func:`~move_on_after` or :func:`~fail_after`, both of which also accept
``shield=True``::

    async def do_something(resource):
        try:
            ...
        except BaseException:
            # Here we wait 10 seconds for resource.aclose() to complete,
            # but if the operation doesn't complete within that period, we move on
            # and re-raise the caught exception anyway
            with move_on_after(10, shield=True):
                await resource.aclose()

            raise

    run(main)

.. _finalization:

Finalization
------------

Sometimes you may want to perform cleanup operations in response to the failure of the
operation::

    async def do_something():
        try:
            await run_async_stuff()
        except BaseException:
            # (perform cleanup)
            raise

In some specific cases, you might only want to catch the cancellation exception. This is
tricky because each async framework has its own exception class for that and AnyIO
cannot control which exception is raised in the task when it's cancelled. To work around
that, AnyIO provides a way to retrieve the exception class specific to the currently
running async framework, using :func:`~get_cancelled_exc_class`::

    from anyio import get_cancelled_exc_class


    async def do_something():
        try:
            await run_async_stuff()
        except get_cancelled_exc_class():
            # (perform cleanup)
            raise

.. warning:: Always reraise the cancellation exception if you catch it. Failing to do so
    may cause undefined behavior in your application.

If you need to use ``await`` during finalization, you need to enclose it in a shielded
cancel scope, or the operation will be cancelled immediately since it's in an already
cancelled scope::

    async def do_something():
        try:
            await run_async_stuff()
        except get_cancelled_exc_class():
            with CancelScope(shield=True):
                await some_cleanup_function()

            raise

.. _cancel_scope_stack_corruption:

Avoiding cancel scope stack corruption
--------------------------------------

When using cancel scopes, it is important that they are entered and exited in LIFO (last
in, first out) order within each task. This is usually not an issue since cancel scopes
are normally used as context managers. However, in certain situations, cancel scope
stack corruption might still occur:

* Manually calling ``CancelScope.__enter__()`` and ``CancelScope.__exit__()``, usually
  from another context manager class, in the wrong order
* Using cancel scopes with ``[Async]ExitStack`` in a manner that couldn't be achieved by
  nesting them as context managers
* Using the low level coroutine protocol to execute parts of the coroutine function in
  different cancel scopes
* Yielding in an async generator while enclosed in a cancel scope

Remember that task groups contain their own cancel scopes so the same list of risky
situations applies to them too.

As an example, the following code is highly dubious::

    # Bad!
    async def some_generator():
        async with create_task_group() as tg:
            tg.start_soon(foo)
            yield

The problem with this code is that it violates structural concurrency: what happens if
the spawned task raises an exception? The host task would be cancelled as a result, but
the host task might be long gone by the time that happens. Even if it weren't, any
enclosing ``try...except`` in the generator would not be triggered. Unfortunately there
is currently no way to automatically detect this condition in AnyIO, so in practice you
may simply experience some weird behavior in your application as a consequence of
running code like above.

Depending on how they are used, this pattern is, however, *usually* safe to use in
asynchronous context managers, so long as you make sure that the same host task keeps
running throughout the entire enclosed code block::

    from contextlib import asynccontextmanager


    # Okay in most cases!
    @asynccontextmanager
    async def some_context_manager():
        async with create_task_group() as tg:
            tg.start_soon(foo)
            yield

Prior to AnyIO 3.6, this usage pattern was also invalid in pytest's asynchronous
generator fixtures. Starting from 3.6, however, each async generator fixture is run from
start to end in the same task, making it possible to have task groups or cancel scopes
safely straddle the ``yield``.

When you're implementing the async context manager protocol manually and your async
context manager needs to use other context managers, you may find it convenient to use
:class:`AsyncContextManagerMixin` in order to avoid cumbersome code that calls
``__aenter__()`` and ``__aexit__()`` directly::

    from __future__ import annotations

    from collections.abc import AsyncGenerator
    from typing import Self

    from anyio import AsyncContextManagerMixin, create_task_group


    class MyAsyncContextManager(AsyncContextManagerMixin):
        @asynccontextmanager
        async def __asynccontextmanager__(self) -> AsyncGenerator[Self]:
            async with create_task_group() as tg:
                ...  # launch tasks
                yield self

.. seealso:: :doc:`contextmanagers`
