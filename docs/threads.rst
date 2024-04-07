Working with threads
====================

.. py:currentmodule:: anyio

Practical asynchronous applications occasionally need to run network, file or
computationally expensive operations. Such operations would normally block the
asynchronous event loop, leading to performance issues. The solution is to run such code
in *worker threads*. Using worker threads lets the event loop continue running other
tasks while the worker thread runs the blocking call.

Running a function in a worker thread
-------------------------------------

To run a (synchronous) callable in a worker thread::

    import time

    from anyio import to_thread, run


    async def main():
        await to_thread.run_sync(time.sleep, 5)

    run(main)

By default, tasks are shielded from cancellation while they are waiting for a worker
thread to finish. You can pass the ``cancellable=True`` parameter to allow such tasks to
be cancelled. Note, however, that the thread will still continue running – only its
outcome will be ignored.

.. seealso:: :ref:`RunInProcess`

Calling asynchronous code from a worker thread
----------------------------------------------

If you need to call a coroutine function from a worker thread, you can do this::

    from anyio import from_thread, sleep, to_thread, run


    def blocking_function():
        from_thread.run(sleep, 5)


    async def main():
        await to_thread.run_sync(blocking_function)

    run(main)

.. note:: The worker thread must have been spawned using :func:`~to_thread.run_sync` for
   this to work.

Calling synchronous code from a worker thread
---------------------------------------------

Occasionally you may need to call synchronous code in the event loop thread from a
worker thread. Common cases include setting asynchronous events or sending data to a
memory object stream. Because these methods aren't thread safe, you need to arrange them
to be called inside the event loop thread using :func:`~from_thread.run_sync`::

    import time

    from anyio import Event, from_thread, to_thread, run

    def worker(event):
        time.sleep(1)
        from_thread.run_sync(event.set)

    async def main():
        event = Event()
        await to_thread.run_sync(worker, event)
        await event.wait()

    run(main)

Calling asynchronous code from an external thread
-------------------------------------------------

If you need to run async code from a thread that is not a worker thread spawned by the
event loop, you need a *blocking portal*. This needs to be obtained from within the
event loop thread.

One way to do this is to start a new event loop with a portal, using
:class:`~from_thread.start_blocking_portal` (which takes mostly the same arguments as
:func:`~run`::

    from anyio.from_thread import start_blocking_portal


    with start_blocking_portal(backend='trio') as portal:
        portal.call(...)

If you already have an event loop running and wish to grant access to external threads,
you can create a :class:`~.BlockingPortal` directly::

    from anyio import run
    from anyio.from_thread import BlockingPortal


    async def main():
        async with BlockingPortal() as portal:
            # ...hand off the portal to external threads...
            await portal.sleep_until_stopped()

    run(main)

Spawning tasks from worker threads
----------------------------------

When you need to spawn a task to be run in the background, you can do so using
:meth:`~.BlockingPortal.start_task_soon`::

    from concurrent.futures import as_completed

    from anyio import sleep
    from anyio.from_thread import start_blocking_portal


    async def long_running_task(index):
        await sleep(1)
        print(f'Task {index} running...')
        await sleep(index)
        return f'Task {index} return value'


    with start_blocking_portal() as portal:
        futures = [portal.start_task_soon(long_running_task, i) for i in range(1, 5)]
        for future in as_completed(futures):
            print(future.result())

Cancelling tasks spawned this way can be done by cancelling the returned
:class:`~concurrent.futures.Future`.

Blocking portals also have a method similar to
:meth:`TaskGroup.start() <.abc.TaskGroup.start>`:
:meth:`~.BlockingPortal.start_task` which, like its counterpart, waits for the callable
to signal readiness by calling ``task_status.started()``::

    from anyio import sleep, TASK_STATUS_IGNORED
    from anyio.from_thread import start_blocking_portal


    async def service_task(*, task_status=TASK_STATUS_IGNORED):
        task_status.started('STARTED')
        await sleep(1)
        return 'DONE'


    with start_blocking_portal() as portal:
        future, start_value = portal.start_task(service_task)
        print('Task has started with value', start_value)

        return_value = future.result()
        print('Task has finished with return value', return_value)


Using asynchronous context managers from worker threads
-------------------------------------------------------

You can use :meth:`~.BlockingPortal.wrap_async_context_manager` to wrap an asynchronous
context managers as a synchronous one::

    from anyio.from_thread import start_blocking_portal


    class AsyncContextManager:
        async def __aenter__(self):
            print('entering')

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            print('exiting with', exc_type)


    async_cm = AsyncContextManager()
    with start_blocking_portal() as portal, portal.wrap_async_context_manager(async_cm):
        print('inside the context manager block')

.. note:: You cannot use wrapped async context managers in synchronous callbacks inside
   the event loop thread.

Context propagation
-------------------

When running functions in worker threads, the current context is copied to the worker
thread. Therefore any context variables available on the task will also be available to
the code running on the thread. As always with context variables, any changes made to
them will not propagate back to the calling asynchronous task.

When calling asynchronous code from worker threads, context is again copied to the task
that calls the target function in the event loop thread.

Adjusting the default maximum worker thread count
-------------------------------------------------

The default AnyIO worker thread limiter has a value of **40**, meaning that any calls
to :func:`.to_thread.run_sync` without an explicit ``limiter`` argument will cause a
maximum of 40 threads to be spawned. You can adjust this limit like this::

    from anyio import to_thread

    async def foo():
        # Set the maximum number of worker threads to 60
        to_thread.current_default_thread_limiter().total_tokens = 60

.. note:: AnyIO's default thread pool limiter does not affect the default thread pool
    executor on :mod:`asyncio`.

Reacting to cancellation in worker threads
------------------------------------------

While there is no mechanism in Python to cancel code running in a thread, AnyIO provides a
mechanism that allows user code to voluntarily check if the host task's scope has been cancelled,
and if it has, raise a cancellation exception. This can be done by simply calling
:func:`from_thread.check_cancelled`::

    from anyio import to_thread, from_thread

    def sync_function():
        while True:
            from_thread.check_cancelled()
            print("Not cancelled yet")
            sleep(1)

    async def foo():
        with move_on_after(3):
            await to_thread.run_sync(sync_function)


Sharing a blocking portal on demand
-----------------------------------

If you're building a synchronous API that needs to start a blocking portal on demand,
you might need a more efficient solution than just starting a blocking portal for each
call. To that end, you can use :class:`BlockingPortalProvider`::

    from anyio.to_thread import BlockingPortalProvider

    class MyAPI:
        def __init__(self, async_obj) -> None:
            self._async_obj = async_obj
            self._portal_provider = BlockingPortalProvider()

        def do_stuff(self) -> None:
            with self._portal_provider as portal:
                portal.call(async_obj.do_async_stuff)

Now, no matter how many threads call the ``do_stuff()`` method on a ``MyAPI`` instance
at the same time, the same blocking portal will be used to handle the async calls
inside. It's easy to see that this is much more efficient than having each call spawn
its own blocking portal.
