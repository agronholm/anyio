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

To run a (synchronous) callable in a worker thread:

.. literalinclude:: snippets/threads/run_sync.py

By default, tasks are shielded from cancellation while they are waiting for a worker
thread to finish. You can pass the ``abandon_on_cancel=True`` parameter to allow such tasks to
be cancelled. Note, however, that the thread will still continue running – only its
outcome will be ignored.

.. seealso:: :ref:`RunInProcess`

Calling asynchronous code from a worker thread
----------------------------------------------

If you need to call a coroutine function from a worker thread, you can do this:

.. literalinclude:: snippets/threads/call_async_from_thread.py

.. note:: The worker thread must have been spawned using :func:`~to_thread.run_sync` for
   this to work.

Calling synchronous code from a worker thread
---------------------------------------------

Occasionally you may need to call synchronous code in the event loop thread from a
worker thread. Common cases include setting asynchronous events or sending data to a
memory object stream. Because these methods aren't thread safe, you need to arrange them
to be called inside the event loop thread using :func:`~from_thread.run_sync`:

.. literalinclude:: snippets/threads/call_sync_from_thread.py

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

The first method is the easier one:

.. literalinclude:: snippets/threads/event_loop_token.py

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
manager and keeping it open:

.. literalinclude:: snippets/threads/blocking_portal.py

The second option uses :func:`~.from_thread.start_blocking_portal` to launch a new
event loop in its own dedicated thread:

.. literalinclude:: snippets/threads/start_blocking_portal.py

.. note:: The event loop is shut down as soon as you exit the context manager.

Calling between event loops
+++++++++++++++++++++++++++

When a blocking portal belongs to an event loop running in another thread, code in an
event loop can use :meth:`~.BlockingPortal.call_async` to call into it without blocking
the calling thread. For example, a server can expose a portal in its existing event
loop so that user code running in a separate event loop can call back into the server::

    from anyio import run, to_thread
    from anyio.from_thread import BlockingPortal


    async def server_operation() -> str:
        return "result from the server's event loop"


    async def user_code(portal: BlockingPortal) -> None:
        result = await portal.call_async(server_operation)
        print(result)


    async def main() -> None:
        async with BlockingPortal() as portal:
            # Run the user-code event loop in a separate thread
            await to_thread.run_sync(run, user_code, portal)


    run(main)

Cancelling the calling task also cancels the task running in the portal.
By default, the caller waits for the task to finish cleaning up. Any exception raised
during cleanup is propagated to the caller; otherwise, the caller's cancellation is
re-raised. Pass ``abandon_on_cancel=True`` to stop waiting immediately after requesting
cancellation and ignore the task's subsequent return value or any raised exception.

Spawning tasks
++++++++++++++

To spawn a task from the blocking portal, you can use
:meth:`~.BlockingPortal.start_task_soon`. It will return a
:class:`~concurrent.futures.Future` object that you can wait on to get the result when
the task finishes:

.. literalinclude:: snippets/threads/start_task_soon.py

Cancelling tasks spawned this way can be done by cancelling the returned
:class:`~concurrent.futures.Future`.

Blocking portals also have a method similar to
:meth:`TaskGroup.start() <.abc.TaskGroup.start>`:
:meth:`~.BlockingPortal.start_task` which, like its counterpart, waits for the callable
to signal readiness by calling ``task_status.started()``:

.. literalinclude:: snippets/threads/start_task.py


Using asynchronous context managers
+++++++++++++++++++++++++++++++++++

You can use :meth:`~.BlockingPortal.wrap_async_context_manager` to wrap an asynchronous
context managers as a synchronous one:

.. literalinclude:: snippets/threads/wrap_async_context_manager.py

.. note:: You cannot use wrapped async context managers in synchronous callbacks inside
   the event loop thread.

Starting an on-demand, shared blocking portal
+++++++++++++++++++++++++++++++++++++++++++++

If you're building a synchronous API that needs to start a blocking portal on demand,
you might need a more efficient solution than just starting a blocking portal for each
call. To that end, you can use :class:`~.from_thread.BlockingPortalProvider`:

.. literalinclude:: snippets/threads/blocking_portal_provider.py

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
maximum of 40 threads to be spawned. You can adjust this limit like this:

.. literalinclude:: snippets/threads/thread_limiter.py

.. note:: AnyIO's default thread pool limiter does not affect the default thread pool
    executor on :mod:`asyncio`.

Reacting to cancellation in worker threads
------------------------------------------

While there is no mechanism in Python to cancel code running in a thread, AnyIO provides
a mechanism that allows user code to voluntarily check if the host task's scope has been
cancelled, and if it has, raise a cancellation exception. This can be done by simply
calling :func:`from_thread.check_cancelled`:

.. literalinclude:: snippets/threads/check_cancelled.py
