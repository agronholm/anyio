Working with threads
====================

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

    from anyio import run_in_thread, run


    async def main():
        await run_in_thread(time.sleep, 5)

    run(main)

Calling asynchronous code from a worker thread
----------------------------------------------

If you need to call a coroutine function from a worker thread, you can do this::

    from anyio import run_async_from_thread, sleep, run_in_thread, run


    def blocking_function():
        run_async_from_thread(sleep, 5)


    async def main():
        await run_in_thread(blocking_function)

    run(main)

.. note:: The worker thread must have been spawned using :func:`~anyio.run_in_thread` for this to
   work.
