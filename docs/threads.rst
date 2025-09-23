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

Accessing the event loop from a foreign thread
----------------------------------------------

If you need to run code in the event loop from a thread that is not an AnyIO worker
thread (that wasn't spawned by :func:`anyio.to_thread.run_sync`), there are two ways you
can do this:

#. Obtain an *event loop token* from :func:`~.lowlevel.current_token` and then pass that
   as ``token`` to either :func:`~.from_thread.run` or :func:`~.from_thread.run_sync`
   (whichever is appropriate)
#. Run a :class:`~.from_thread.BlockingPortal` in an existing task and make the portal
   object available to the external thread

The first method is the easier one::

    from threading import Thread

    from anyio import Event, run, from_thread
    from anyio.lowlevel import current_token

    def external_func(event, token):
        # Enter the event loop using the given token to set the asynchronous event
        from_thread.run_sync(event.set, token=token)

    async def main():
        event = Event()

        # Start a new thread, independent of AnyIO's worker threads
        thread = Thread(target=external_func, args=[event, current_token()])
        thread.start()

        # Wait for the external thread to set the event
        await event.wait()

    run(main)

The next section will demonstrate how to do the same with blocking portals.

Running code from threads using blocking portals
------------------------------------------------

Blocking portals (:class:`~.from_thread.BlockingPortal`) offer a somewhat more
comprehensive array of functionality for accessing event loops from other threads than
just running one-off functions with :func:`~.from_thread.run` or
:func:`~.from_thread.run_sync`. A blocking portal runs its own task group, allowing the
portal to spawn new tasks and thus offer extra functionality that requires task
spawning, such as wrapping asynchronous context managers.

Starting a blocking portal
++++++++++++++++++++++++++

There are two principal ways to create a blocking portal:

#. Running it in a task in an existing event loop
#. Starting a dedicated event loop in a new thread

The first option involves using a :class:`~.BlockingPortal` instance as an async context
manager and keeping it open::

    from anyio import to_thread, run
    from anyio.from_thread import BlockingPortal


    async def async_func() -> None:
        print("This runs on the event loop")


    def sync_func_run_in_thread(portal: BlockingPortal) -> None:
        portal.call(async_func)


    async def main():
        async with BlockingPortal() as portal:
            # Here the portal stays open until the worker thread has run the function
            await to_thread.run_sync(sync_func_run_in_thread, portal)


    run(main)

The second option using :func:`~.from_thread.start_blocking_portal` to launch a new
event loop in its own dedicated thread::

    from anyio.from_thread import start_blocking_portal


    async def async_func() -> None:
        print("This runs on the event loop")


    with start_blocking_portal() as portal:
        portal.call(async_func)

.. note:: The event loop is shut down as soon as you exit the context manager.

Spawning tasks
++++++++++++++

To spawn a task from the blocking portal, you can use
:meth:`~.BlockingPortal.start_task_soon`. It will return a
:class:`~concurrent.futures.Future` object that you can wait on to get the result when
the task finishes::

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


Using asynchronous context managers
+++++++++++++++++++++++++++++++++++

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

Starting an on-demand, shared blocking portal
+++++++++++++++++++++++++++++++++++++++++++++

If you're building a synchronous API that needs to start a blocking portal on demand,
you might need a more efficient solution than just starting a blocking portal for each
call. To that end, you can use :class:`~.from_thread.BlockingPortalProvider`::

    from anyio.from_thread import BlockingPortalProvider

    class MyAPI:
        def __init__(self, async_obj) -> None:
            self._async_obj = async_obj
            self._portal_provider = BlockingPortalProvider()

        def do_stuff(self) -> None:
            with self._portal_provider as portal:
                portal.call(self._async_obj.do_async_stuff)

Now, no matter how many threads call the ``do_stuff()`` method on a ``MyAPI`` instance
at the same time, the same blocking portal will be used to handle the async calls
inside. It's easy to see that this is much more efficient than having each call spawn
its own blocking portal.

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

While there is no mechanism in Python to cancel code running in a thread, AnyIO provides
a mechanism that allows user code to voluntarily check if the host task's scope has been
cancelled, and if it has, raise a cancellation exception. This can be done by simply
calling :func:`from_thread.check_cancelled`::

    import time

    from anyio import to_thread, from_thread, move_on_after

    def sync_function():
        while True:
            from_thread.check_cancelled()
            print("Not cancelled yet")
            time.sleep(1)

    async def foo():
        with move_on_after(3):
            await to_thread.run_sync(sync_function)
