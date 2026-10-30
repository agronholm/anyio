Using synchronization primitives
================================

.. py:currentmodule:: anyio

Synchronization primitives are objects that are used by tasks to communicate and
coordinate with each other. They are useful for things like distributing workload,
notifying other tasks and guarding access to shared resources.

.. note:: AnyIO primitives are not thread-safe, therefore they should not be used
   directly from worker threads.  Use :func:`~from_thread.run_sync` for that.

Events
------

Events (:class:`Event`) are used to notify tasks that something they've been waiting to
happen has happened. An event object can have multiple listeners and they are all
notified when the event is triggered.

Example:

.. literalinclude:: snippets/synchronization/event.py

.. note:: Unlike standard library Events, AnyIO events cannot be reused, and must be
   replaced instead. This practice prevents a class of race conditions, and matches the
   semantics of the Trio library.

Semaphores
----------

Semaphores (:class:`Semaphore`) are used for limiting access to a shared resource. A
semaphore starts with a maximum value, which is decremented each time the semaphore is
acquired by a task and incremented when it is released. If the value drops to zero, any
attempt to acquire the semaphore will block until another task frees it.

Example:

.. literalinclude:: snippets/synchronization/semaphore.py

.. tip:: If the performance of semaphores is critical for you, you could pass
   ``fast_acquire=True`` to :class:`Semaphore`. This has the effect of skipping the
   :func:`~.lowlevel.cancel_shielded_checkpoint` call in :meth:`Semaphore.acquire` if
   there is no contention (acquisition succeeds immediately). This could, in some cases,
   lead to the task never yielding control back to to the event loop if you use the
   semaphore in a loop that does not have other yield points.

Locks
-----

Locks (:class:`Lock`) are used to guard shared resources to ensure sole access to a
single task at once. They function much like semaphores with a maximum value of 1,
except that only the task that acquired the lock is allowed to release it.

Example:

.. literalinclude:: snippets/synchronization/lock.py

.. tip:: If the performance of locks is critical for you, you could pass
   ``fast_acquire=True`` to :class:`Lock`. This has the effect of skipping the
   :func:`~.lowlevel.cancel_shielded_checkpoint` call in :meth:`Lock.acquire` if there
   is no contention (acquisition succeeds immediately). This could, in some cases, lead
   to the task never yielding control back to to the event loop if use the lock in a
   loop that does not have other yield points.

Conditions
----------

A condition is basically a combination of an event and a lock. It first acquires a lock
and then waits for a notification from the event. Once the condition receives a
notification, it releases the lock. The notifying task can also choose to wake up more
than one listener at once, or even all of them.

Like :class:`Lock`, :class:`Condition` also requires that the task which locked it also
the one to release it.

Example:

.. literalinclude:: snippets/synchronization/condition.py

.. _capacity-limiters:

Capacity limiters
-----------------

Capacity limiters (:class:`CapacityLimiter`) are like semaphores except that a single
borrower (the current task by default) can only hold a single token at a time. It is
also possible to borrow a token on behalf of any arbitrary object, so long as that object
is hashable.

It is recommended to use capacity limiters instead of semaphores unless you intend to
allow a task to acquire multiple tokens from the same object. AnyIO uses capacity
limiters to limit the number of threads spawned.

The number of total tokens available for tasks to acquire can be adjusted by assigning
the desired value to the ``total_tokens`` property. If the value is higher than the
previous one, it will automatically wake up the appropriate number of waiting tasks.

Example:

.. literalinclude:: snippets/synchronization/capacity_limiter.py

Resource guards
---------------

Some resources, such as sockets, are very sensitive about concurrent use and should not
allow even attempts to be used concurrently. For such cases, :class:`ResourceGuard` is
the appropriate solution:

.. literalinclude:: snippets/synchronization/resource_guard.py

Now, if another task tries calling the ``do_something()`` method on the same
``Resource`` instance before the first call has finished, that will raise a
:exc:`BusyResourceError`.

Queues
------

In place of queues, AnyIO offers a more powerful construct:
:ref:`memory object streams <memory object streams>`.

Futures
-------

Futures (:class:`Future`) are used to hand a result, an exception, or a cancellation from
one task to another. Once a future object is resolved, awaiting it again immediately returns or
raises the same outcome.

Example:

.. literalinclude:: snippets/synchronization/future.py

A future can also finish with an exception instead of a value, or be cancelled before
it finishes at all. Assigning an exception to :attr:`~Future.exception` puts the future into the
:attr:`~Future.Status.FAILED` state; awaiting it then raises :exc:`FutureFailed`, with
the original exception attached as ``__cause__``. Calling :meth:`~Future.cancel` puts it
into the :attr:`~Future.Status.CANCELLED` state instead, and awaiting it raises :exc:`FutureCancelled`.
To check which of these states a future ended up in without triggering either exception,
use :meth:`~Future.wait` and inspect :attr:`~Future.status`:

.. literalinclude:: snippets/synchronization/future_exception.py

.. note:: If you're coming from :mod:`asyncio`, :class:`Future` differs from
   :class:`asyncio.Future` in a few ways:

   * Results and exceptions are set via the :attr:`~Future.return_value` and
     :attr:`~Future.exception` attributes, rather than :meth:`asyncio.Future.set_result`` and
     :meth:`asyncio.Future.set_exception` methods.
   * Unlike :meth:`asyncio.Future.cancel`, :meth:`anyio.Future.cancel` takes no arguments.
   * Awaiting a failed future raises :exc:`FutureFailed` rather than the original
     exception; the original exception is available as ``__cause__``.
   * The equivalent for :meth:`asyncio.Future.cancelled` is to check
     ``future.status is Future.Status.CANCELLED``.
   * The equivalent for :meth:`asyncio.Future.done` is to check
     ``future.status is not Future.Status.PENDING``.
   * There is (by design) no equivalent for :meth:`asyncio.Future.add_done_callback`.
     Either await the future directly or call :meth:`~Future.wait` in another task.
