Cancellation and timeouts
=========================

The ability to cancel tasks is the foremost advantage of the asynchronous programming model.
Threads, on the other hand, cannot be forcibly killed and shutting them down will require perfect
cooperation from the code running in them.

Cancellation in AnyIO follows the model established by the trio_ framework. This means that
cancellation of tasks is done via so called *cancel scopes*. Cancel scopes are used as context
managers and can be nested. Cancelling a cancel scope cancels all cancel scopes nested within it.
If a task is waiting on something, it is cancelled immediately. If the task is just starting, it
will run until it first tries to run an operation requiring waiting, such as :func:`~anyio.sleep`.

A task group contains its own cancel scope. The entire task group can be cancelled by cancelling
this scope.

.. _trio: https://trio.readthedocs.io/en/latest/reference-core.html#cancellation-and-timeouts

Timeouts
--------

Networked operations can often take a long time, and you usually want to set up some kind of a
timeout to ensure that your application doesn't stall forever. There are two principal ways to do
this: :func:`~anyio.move_on_after` and :func:`~anyio.fail_after`. Both are used as asynchronous
context managers. The difference between these two is that the former simply exits the context
block prematurely on a timeout, while the other raises a :exc:`TimeoutError`.

Both methods create a new cancel scope, and you can check the deadline by accessing the
:attr:`~anyio.abc.CancelScope.deadline` attribute. Note, however, that an outer cancel scope may
have an earlier deadline than your current cancel scope. To check the actual deadline, you can use
the :func:`~anyio.current_effective_deadline` function.

Here's how you typically use timeouts::

    from anyio import create_task_group, move_on_after, sleep, run


    async def main():
        async with create_task_group() as tg:
            async with move_on_after(1) as scope:
                print('Starting sleep')
                await sleep(2)
                print('This should never be printed')

            # The cancel_called property will be True if timeout was reached
            print('Exited cancel scope, cancelled =', scope.cancel_called)

    run(main)

Shielding
---------

There are cases where you want to shield your task from cancellation, at least temporarily.
The most important such use case is performing shutdown procedures on asynchronous resources.

To accomplish this, open a new cancel scope with the ``shield=True`` argument::

    from anyio import create_task_group, open_cancel_scope, sleep, run


    async def external_task():
        print('Started sleeping in the external task')
        await sleep(1)
        print('This line should never be seen')


    async def main():
        async with create_task_group() as tg:
            async with open_cancel_scope(shield=True) as scope:
                await tg.spawn(external_task)
                await tg.cancel_scope.cancel()
                print('Started sleeping in the host task')
                await sleep(1)
                print('Finished sleeping in the host task')

    run(main)

The shielded block will be exempt from cancellation except when the shielded block itself is being
cancelled. Shieldin a cancel scope is often best combined with :func:`~anyio.move_on_after` or
:func:`~anyio.fail_after`, both of which also accept ``shield=True``.

Finalization
------------

Sometimes you may want to perform cleanup operations in response to the failure of the operation::

    async def do_something():
        try:
            await run_async_stuff()
        except BaseException:
            # (perform cleanup)
            raise

In some specific cases, you might only want to catch the cancellation exception. This is tricky
because each async framework has its own exception class for that and AnyIO cannot control which
exception is raised in the task when it's cancelled. To work around that, AnyIO provides a way to
retrieve the exception class specific to the currently running async framework, using
:func:`~anyio.get_cancelled_exc_class`::

    from anyio import get_cancelled_exc_class


    async def do_something():
        try:
            await run_async_stuff()
        except get_cancelled_exc_class():
            # (perform cleanup)
            raise

.. warning:: Always reraise the cancellation exception if you catch it. Failing to do so may cause
             undefined behavior in your application.
