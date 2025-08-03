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

Example::

    from anyio import Event, create_task_group, run


    async def notify(event):
        event.set()


    async def main():
        event = Event()
        async with create_task_group() as tg:
            tg.start_soon(notify, event)
            await event.wait()
            print('Received notification!')

    run(main)

    # Output:
    # Received notification!

.. note:: Unlike standard library Events, AnyIO events cannot be reused, and must be
   replaced instead. This practice prevents a class of race conditions, and matches the
   semantics of the Trio library.

Semaphores
----------

Semaphores (:class:`Semaphore`) are used for limiting access to a shared resource. A
semaphore starts with a maximum value, which is decremented each time the semaphore is
acquired by a task and incremented when it is released. If the value drops to zero, any
attempt to acquire the semaphore will block until another task frees it.

Example::

    from anyio import Semaphore, create_task_group, sleep, run


    async def use_resource(tasknum, semaphore):
        async with semaphore:
            print(f"Task number {tasknum} is now working with the shared resource")
            await sleep(1)


    async def main():
        semaphore = Semaphore(2)
        async with create_task_group() as tg:
            for num in range(10):
                tg.start_soon(use_resource, num, semaphore)

    run(main)

    # Output:
    # Task number 0 is now working with the shared resource
    # Task number 1 is now working with the shared resource
    # Task number 2 is now working with the shared resource
    # Task number 3 is now working with the shared resource
    # Task number 4 is now working with the shared resource
    # Task number 5 is now working with the shared resource
    # Task number 6 is now working with the shared resource
    # Task number 7 is now working with the shared resource
    # Task number 8 is now working with the shared resource
    # Task number 9 is now working with the shared resource

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

Example::

    from anyio import Lock, create_task_group, sleep, run


    async def use_resource(tasknum, lock):
        async with lock:
            print('Task number', tasknum, 'is now working with the shared resource')
            await sleep(1)


    async def main():
        lock = Lock()
        async with create_task_group() as tg:
            for num in range(4):
                tg.start_soon(use_resource, num, lock)

    run(main)

    # Output:
    # Task number 0 is now working with the shared resource
    # Task number 1 is now working with the shared resource
    # Task number 2 is now working with the shared resource
    # Task number 3 is now working with the shared resource

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

Example::

    from anyio import Condition, create_task_group, sleep, run


    async def listen(tasknum, condition):
        async with condition:
            await condition.wait()
            print('Woke up task number', tasknum)


    async def main():
        condition = Condition()
        async with create_task_group() as tg:
            for tasknum in range(6):
                tg.start_soon(listen, tasknum, condition)

            await sleep(1)
            async with condition:
                condition.notify(1)

            await sleep(1)
            async with condition:
                condition.notify(2)

            await sleep(1)
            async with condition:
                condition.notify_all()

    run(main)

    # Output:
    # Woke up task number 0
    # Woke up task number 1
    # Woke up task number 2
    # Woke up task number 3
    # Woke up task number 4
    # Woke up task number 5

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

Example::

    from anyio import CapacityLimiter, create_task_group, sleep, run


    async def use_resource(tasknum, limiter):
        async with limiter:
            print(f"Task number {tasknum} is now working with the shared resource")
            await sleep(1)


    async def main():
        limiter = CapacityLimiter(2)
        async with create_task_group() as tg:
            for num in range(10):
                tg.start_soon(use_resource, num, limiter)

    run(main)

    # Output:
    # Task number 0 is now working with the shared resource
    # Task number 1 is now working with the shared resource
    # Task number 2 is now working with the shared resource
    # Task number 3 is now working with the shared resource
    # Task number 4 is now working with the shared resource
    # Task number 5 is now working with the shared resource
    # Task number 6 is now working with the shared resource
    # Task number 7 is now working with the shared resource
    # Task number 8 is now working with the shared resource
    # Task number 9 is now working with the shared resource

Resource guards
---------------

Some resources, such as sockets, are very sensitive about concurrent use and should not
allow even attempts to be used concurrently. For such cases, :class:`ResourceGuard` is
the appropriate solution::

    class Resource:
        def __init__(self):
            self._guard = ResourceGuard()

        async def do_something() -> None:
            with self._guard:
                ...

Now, if another task tries calling the ``do_something()`` method on the same
``Resource`` instance before the first call has finished, that will raise a
:exc:`BusyResourceError`.

Queues
------

In place of queues, AnyIO offers a more powerful construct:
:ref:`memory object streams <memory object streams>`.
