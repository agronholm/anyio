Using synchronization primitives
================================

Synchronization primitives are objects that are used by tasks to communicate and coordinate with
each other. They are useful for things like distributing workload, notifying other tasks and
guarding access to shared resources.

Semaphores
----------

Semaphores are used for limiting access to a shared resource. A semaphore starts with a maximum
value, which is decremented each time the semaphore is acquired by a task and incremented when it
is released. If the value drops to zero, any attempt to acquire the semaphore will block until
another task frees it.

Example::

    from anyio import create_task_group, create_semaphore, sleep, run


    async def use_resource(tasknum, semaphore):
        async with semaphore:
            print('Task number', tasknum, 'is now working with the shared resource')
            await sleep(1)


    async def main():
        semaphore = create_semaphore(2)
        async with create_task_group() as tg:
            for num in range(10):
                await tg.spawn(use_resource, num, semaphore)

    run(main)

Locks
-----

Locks are used to guard shared resources to ensure sole access to a single task at once.
They function much like semaphores with a maximum value of 1.

Example::

    from anyio import create_task_group, create_lock, sleep, run


    async def use_resource(tasknum, lock):
        async with lock:
            print('Task number', tasknum, 'is now working with the shared resource')
            await sleep(1)


    async def main():
        lock = create_lock()
        async with create_task_group() as tg:
            for num in range(4):
                await tg.spawn(use_resource, num, lock)

    run(main)

Events
------

Events are used to notify tasks that something they've been waiting to happen has happened.
An event object can have multiple listeners and they are all notified when the event is triggered.
Events can also be reused by clearing the triggered state.

Example::

    from anyio import create_task_group, create_event, run


    async def notify(event):
        await event.set()


    async def main():
        event = create_event()
        async with create_task_group() as tg:
            await tg.spawn(notify, event)
            await event.wait()
            print('Received notification!')

    run(main)

Conditions
----------

A condition is basically a combination of an event and a lock. It first acquires a lock and then
waits for a notification from the event. Once the condition receives a notification, it releases
the lock. The notifying task can also choose to wake up more than one listener at once, or even
all of them.

Example::

    from anyio import create_task_group, create_condition, sleep, run


    async def listen(tasknum, condition):
        async with condition:
            await condition.wait()
            print('Woke up task number', tasknum)


    async def main():
        condition = create_condition()
        async with create_task_group() as tg:
            for tasknum in range(6):
                await tg.spawn(listen, tasknum, condition)

            await sleep(1)
            async with condition:
                await condition.notify(1)

            await sleep(1)
            async with condition:
                await condition.notify(2)

            await sleep(1)
            async with condition:
                await condition.notify_all()

    run(main)

Capacity limiters
-----------------

Capacity limiters are like semaphores except that a single borrower (the current task by default)
can only hold a single token at a time. It is also possible to borrow a token on behalf of any
arbitrary object, so long as that object is hashable.

Example::

    from anyio import create_task_group, create_capacity_limiter, sleep, run


    async def use_resource(tasknum, limiter):
        async with limiter:
            print('Task number', tasknum, 'is now working with the shared resource')
            await sleep(1)


    async def main():
        limiter = create_capacity_limiter(2)
        async with create_task_group() as tg:
            for num in range(10):
                await tg.spawn(use_resource, num, limiter)

    run(main)

To adjust the number of total tokens, you can use the
:meth:`~anyio.abc.CapacityLimiter.set_total_tokens` method.

Memory object streams
---------------------

Memory object streams are intended for implementing a producer-consumer pattern with multiple
tasks. Using :func:`~anyio.create_memory_object_stream`, you get a pair of object streams: one for
sending, one for receiving.

By default, memory object streams are created with a buffer size of 0. This means that
:meth:`~anyio.synchronization.MemoryObjectSendStream.send` will block until there's another task
that calls :meth:`~anyio.synchronization.MemoryObjectReceiveStream.receive`. You can set the buffer
size to a value of your choosing when creating the stream. It is also possible to have an unbounded
buffer by passing :data:``math.inf`` as the buffer size but this is not recommended.

Memory object streams can be cloned by calling the ``clone()`` method. Each clone can be closed
separately, but each end of the stream is only considered closed once all of its clones have been
closed. For example, if you have two clones of the receive stream, the send stream will start
raising :exc:`~anyio.exceptions.BrokenResourceError` only when both receive streams have been
closed.

Multiple tasks can send and receive on the same memory object stream (or its clones) but each sent
item is only ever delivered to a single recipient.

The receive ends of memory object streams can be iterated using the async iteration protocol.
The loop exits when all clones of the send stream have been closed.

Example::

    from anyio import create_task_group, create_memory_object_stream, run


    async def process_items(receive_stream):
        async with receive_stream:
            async for item in receive_stream:
                print('received', item)


    async def main():
        send_stream, receive_stream = create_memory_object_stream()
        async with create_task_group() as tg:
            await tg.spawn(process_items, receive_stream)
            async with send_stream:
                for num in range(10):
                    await send_stream.send(f'number {num}')

    run(main)
