Working with threads
====================

.. py:currentmodule:: anyio

Practical asynchronous applications occasionally need to run network, file or computationally
expensive operations. Such operations would normally block the asynchronous event loop, leading to
performance issues. The solution is to run such code in *worker threads*. Using worker threads lets
the event loop continue running other tasks while the worker thread runs the blocking call.

 .. caution:: Do not spawn too many threads, as the context switching overhead may cause your
    system to slow down to a crawl. A few dozen threads should be fine, but hundreds are probably
    bad. Consider using AnyIO's semaphores to limit the maximum number of threads.

Running a function in a worker thread
-------------------------------------

To run a (synchronous) callable in a worker thread::

    import time

    from anyio import to_thread, run


    async def main():
        await to_thread.run_sync(time.sleep, 5)

    run(main)

By default, tasks are shielded from cancellation while they are waiting for a worker thread to
finish. You can pass the ``cancellable=True`` parameter to allow such tasks to be cancelled.
Note, however, that the thread will still continue running – only its outcome will be ignored.

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

.. note:: The worker thread must have been spawned using :func:`~run_sync_in_worker_thread`
   for this to work.

Calling synchronous code from a worker thread
---------------------------------------------

Occasionally you may need to call synchronous code in the event loop thread from a worker thread.
Common cases include setting asynchronous events or sending data to a memory object stream.
Because these methods aren't thread safe, you need to arrange them to be called inside the event
loop thread using :func:`~from_thread.run_sync`::

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

If you need to run async code from a thread that is not a worker thread spawned by the event loop,
you need a *blocking portal*. This needs to be obtained from within the event loop thread.

One way to do this is to start a new event loop with a portal, using
:func:`~start_blocking_portal` (which takes mostly the same arguments as :func:`~run`::

    from anyio.from_thread import start_blocking_portal


    with start_blocking_portal(backend='trio') as portal:
        portal.call(...)

If you already have an event loop running and wish to grant access to external threads, you can
create a :class:`~.BlockingPortal` directly::

    from anyio import run
    from anyio.from_thread import BlockingPortal


    async def main():
        async with BlockingPortal() as portal:
            # ...hand off the portal to external threads...
            await portal.sleep_until_stopped()

    anyio.run(main)

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

Blocking portals also have a method similar to :meth:`TaskGroup.start() <.abc.TaskGroup.start>`:
:meth:`~.BlockingPortal.start_task` which, like its counterpart, waits for the callable to signal
readiness by calling ``task_status.started()``::

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

You can use :meth:`~.BlockingPortal.wrap_async_context_manager` to wrap an asynchronous context
managers as a synchronous one::

    from anyio.from_thread import start_blocking_portal


    class AsyncContextManager:
        async def __aenter__(self):
            print('entering')

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            print('exiting with', exc_type)


    async_cm = AsyncContextManager()
    with start_blocking_portal() as portal, portal.wrap_async_context_manager(async_cm):
        print('inside the context manager block')

.. note:: You cannot use wrapped async context managers in synchronous callbacks inside the event
          loop thread.
