Creating and managing tasks
===========================

A *task* is a unit of execution that lets you do many things concurrently that need waiting on.
This works so that while you can have any number of tasks, the asynchronous event loop can only
run one of them at a time. When the task encounters an ``await`` statement that requires the task
to sleep until something happens, the event loop is then free to work on another task. When the
thing the first task was waiting is complete, the event loop will resume the execution of that task
on the first opportunity it gets.

Task handling in AnyIO loosely follows the trio_ model. Tasks can be created (*spawned*) using
*task groups*. A task group is an asynchronous context manager that makes sure that all its child
tasks are finished one way or another after the context block is exited. If a child task, or the
code in the enclosed context block raises an exception, all child tasks are cancelled. Otherwise
the context manager just waits until all child tasks have exited before proceeding.

Here's a demonstration::

    from anyio import sleep, create_task_group, run


    async def sometask(num):
        print('Task', num, 'running')
        await sleep(1)
        print('Task', num, 'finished')


    async def main():
        async with create_task_group() as tg:
            for num in range(5):
                await tg.spawn(sometask, num)

        print('All tasks finished!')

    run(main)

.. _trio: https://trio.readthedocs.io/en/latest/reference-core.html#tasks-let-you-do-multiple-things-at-once

Handling multiple errors in a task group
----------------------------------------

It is possible for more than one task to raise an exception in a task group. This can happen when
a task reacts to cancellation by entering either an exception handler block or a ``finally:``
block and raises an exception there. This raises the question: which exception is propagated from
the task group context manager? The answer is "both". In practice this means that a special
exception, :exc:`~anyio.exceptions.TaskGroupError` is raised which contains both exception objects.
Unfortunately this complicates any code that wishes to catch a specific exception because it could
be wrapped in a :exc:`~anyio.exceptions.TaskGroupError`.
