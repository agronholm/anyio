Working with threads
====================

.. py:currentmodule:: anyio

Practical asynchronous applications occasionally need to run network, file or computationally
expensive operations. Such operations would normally block the asynchronous event loop, leading to
performance issues. To solution is to run such code in *worker threads*. Using worker threads lets
the event loop continue running other tasks while the worker thread runs the blocking call.

 .. caution:: Do not spawn too many threads, as the context switching overhead may cause your
    system to slow down to a crawl. A few dozen threads should be fine, but hundreds are probably
    bad. Consider using AnyIO's semaphores to limit the maximum number of threads.

Running a function in a worker thread
-------------------------------------

To run a (synchronous) callable in a worker thread::

    import time

    from anyio import run_sync_in_worker_thread, run


    async def main():
        await run_sync_in_worker_thread(time.sleep, 5)

    run(main)

By default, tasks are shielded from cancellation while they are waiting for a worker thread to
finish. You can pass the ``cancellable=True`` parameter to allow such tasks to be cancelled.
Note, however, that the thread will still continue running – only its outcome will be ignored.

Calling asynchronous code from a worker thread
----------------------------------------------

If you need to call a coroutine function from a worker thread, you can do this::

    from anyio import run_async_from_thread, sleep, run_sync_in_worker_thread, run


    def blocking_function():
        run_async_from_thread(sleep, 5)


    async def main():
        await run_sync_in_worker_thread(blocking_function)

    run(main)

.. note:: The worker thread must have been spawned using :func:`~run_sync_in_worker_thread`
   for this to work.

Calling asynchronous code from an external thread
-------------------------------------------------

If you need to run async code from a thread that is not a worker thread spawned by the event loop,
you need a *blocking portal*. This needs to be obtained from within the event loop thread.

One way to do this is to start a new event loop with a portal, using
:func:`~start_blocking_portal` (which takes mostly the same arguments as :func:`~run`::

    from anyio import start_blocking_portal


    portal = start_blocking_portal(backend='trio')
    portal.call(...)

    # At the end of your application, stop the portal
    portal.stop_from_external_thread()

Or, you can it as a context manager if that suits your use case::

    with start_blocking_portal(backend='trio') as portal:
        portal.call(...)

If you already have an event loop running and wish to grant access to external threads, you can
use :func:`~create_blocking_portal` directly::

    from anyio import create_blocking_portal, run


    async def main():
        async with create_blocking_portal() as portal:
            # ...hand off the portal to external threads...
            await portal.sleep_until_stopped()

    anyio.run(main)
