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

Events are used to notify tasks that something they've been waiting to happen has
happened. An event object can have multiple listeners and they are all notified when the
event is triggered.

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

.. note:: Unlike standard library Events, AnyIO events cannot be reused, and must be
   replaced instead. This practice prevents a class of race conditions, and matches the
   semantics of the Trio library.

Semaphores
----------

Semaphores are used for limiting access to a shared resource. A semaphore starts with a
maximum value, which is decremented each time the semaphore is acquired by a task and
incremented when it is released. If the value drops to zero, any attempt to acquire the
semaphore will block until another task frees it.

Example::

    from anyio import Semaphore, create_task_group, sleep, run


    async def use_resource(tasknum, semaphore):
        async with semaphore:
            print('Task number', tasknum, 'is now working with the shared resource')
            await sleep(1)


    async def main():
        semaphore = Semaphore(2)
        async with create_task_group() as tg:
            for num in range(10):
                tg.start_soon(use_resource, num, semaphore)

    run(main)

Locks
-----

Locks are used to guard shared resources to ensure sole access to a single task at once.
They function much like semaphores with a maximum value of 1, except that only the task
that acquired the lock is allowed to release it.

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

Capacity limiters
-----------------

Capacity limiters are like semaphores except that a single borrower (the current task by
default) can only hold a single token at a time. It is also possible to borrow a token
on behalf of any arbitrary object, so long as that object is hashable.

Example::

    from anyio import CapacityLimiter, create_task_group, sleep, run


    async def use_resource(tasknum, limiter):
        async with limiter:
            print('Task number', tasknum, 'is now working with the shared resource')
            await sleep(1)


    async def main():
        limiter = CapacityLimiter(2)
        async with create_task_group() as tg:
            for num in range(10):
                tg.start_soon(use_resource, num, limiter)

    run(main)

You can adjust the total number of tokens by setting a different value on the limiter's
``total_tokens`` property.

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
