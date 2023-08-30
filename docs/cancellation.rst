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
cancelling this scope.

.. _Trio: https://trio.readthedocs.io/en/latest/reference-core.html
   #cancellation-and-timeouts

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
``shield=True``.

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
running async framework, using:func:`~get_cancelled_exc_class`::

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

    # Okay in most cases!
    @async_context_manager
    async def some_context_manager():
        async with create_task_group() as tg:
            tg.start_soon(foo)
            yield

Prior to AnyIO 3.6, this usage pattern was also invalid in pytest's asynchronous
generator fixtures. Starting from 3.6, however, each async generator fixture is run from
start to end in the same task, making it possible to have task groups or cancel scopes
safely straddle the ``yield``.

When you're implementing the async context manager protocol manually and your async
context manager needs to use other context managers, you may find it necessary to call
their ``__aenter__()`` and ``__aexit__()`` directly. In such cases, it is absolutely
vital to ensure that their ``__aexit__()`` methods are called in the exact reverse order
of the ``__aenter__()`` calls. To this end, you may find the
:class:`~contextlib.AsyncExitStack` class very useful::

    from contextlib import AsyncExitStack

    from anyio import create_task_group


    class MyAsyncContextManager:
        async def __aenter__(self):
            self._exitstack = AsyncExitStack()
            await self._exitstack.__aenter__()
            self._task_group = await self._exitstack.enter_async_context(
                create_task_group()
            )

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            return await self._exitstack.__aexit__(exc_type, exc_val, exc_tb)
