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

Queues
------

Queues are used to send objects between tasks. Queues have two central concepts:

* Producers add things to the queue
* Consumers take things from the queue

When an item is inserted into the queue, it will be given to the next consumer that tries to get
an item from the queue. Each item is only ever given to a single consumer.

Queues have a maximum capacity which is determined on creation and cannot be changed later.
When the queue is full, any attempt to put an item to it will block until a consumer retrieves an
item from the queue. If you wish to avoid blocking on either operation, you can use the
:meth:`~anyio.abc.Queue.full` and :meth:`~anyio.abc.Queue.empty` methods to find out about either
condition.

Example::

    from anyio import create_task_group, create_queue, sleep, run


    async def produce(queue):
        for number in range(10):
            await queue.put(number)
            await sleep(1)


    async def main():
        queue = create_queue(100)
        async with create_task_group() as tg:
            await tg.spawn(produce, queue)
            while True:
                number = await queue.get()
                print(number)
                if number == 9:
                    break

    run(main)
