Creating and managing tasks
===========================

.. py:currentmodule:: anyio

A *task* is a unit of execution that lets you do many things concurrently that need
waiting on. This works so that while you can have any number of tasks, the asynchronous
event loop can only run one of them at a time. When the task encounters an ``await``
statement that requires the task to sleep until something happens, the event loop is
then free to work on another task. When the thing the first task was waiting is
complete, the event loop will resume the execution of that task on the first opportunity
it gets.

Task handling in AnyIO loosely follows the Trio_ model. Tasks can be created (*spawned*)
using *task groups*. A task group is an asynchronous context manager that makes sure
that all its child tasks are finished one way or another after the context block is
exited. If a child task, or the code in the enclosed context block raises an exception,
all child tasks are cancelled. Otherwise the context manager just waits until all child
tasks have exited before proceeding.

Here's a demonstration::

    from anyio import sleep, create_task_group, run


    async def sometask(num: int) -> None:
        print('Task', num, 'running')
        await sleep(1)
        print('Task', num, 'finished')


    async def main() -> None:
        async with create_task_group() as tg:
            for num in range(5):
                tg.start_soon(sometask, num)

        print('All tasks finished!')

    run(main)

.. _Trio: https://trio.readthedocs.io/en/latest/reference-core.html
   #tasks-let-you-do-multiple-things-at-once

.. _start_initialize:

Starting and initializing tasks
-------------------------------

Sometimes it is very useful to be able to wait until a task has successfully initialized
itself. For example, when starting network services, you can have your task start the
listener and then signal the caller that initialization is done. That way, the caller
can now start another task that depends on that service being up and running. Also, if
the socket bind fails or something else goes wrong during initialization, the exception
will be propagated to the caller which can then catch and handle it.

This can be done with :meth:`TaskGroup.start() <.abc.TaskGroup.start>`::

    from anyio import (
        TASK_STATUS_IGNORED,
        create_task_group,
        connect_tcp,
        create_tcp_listener,
        run,
    )
    from anyio.abc import TaskStatus


    async def handler(stream):
        ...


    async def start_some_service(
        port: int, *, task_status: TaskStatus[None] = TASK_STATUS_IGNORED
    ):
        async with await create_tcp_listener(
            local_host="127.0.0.1", local_port=port
        ) as listener:
            task_status.started()
            await listener.serve(handler)


    async def main():
        async with create_task_group() as tg:
            await tg.start(start_some_service, 5000)
            async with await connect_tcp("127.0.0.1", 5000) as stream:
                ...


    run(main)

The target coroutine function **must** call ``task_status.started()`` because the task
that is calling with :meth:`TaskGroup.start() <.abc.TaskGroup.start>` will be blocked
until then. If the spawned task never calls it, then the
:meth:`TaskGroup.start() <.abc.TaskGroup.start>` call will raise a ``RuntimeError``.

.. note:: Unlike :meth:`~.abc.TaskGroup.start_soon`, :meth:`~.abc.TaskGroup.start` needs
   an ``await``.

Handling multiple errors in a task group
----------------------------------------

It is possible for more than one task to raise an exception in a task group. This can
happen when a task reacts to cancellation by entering either an exception handler block
or a ``finally:`` block and raises an exception there. This raises the question: which
exception is propagated from the task group context manager? The answer is "both". In
practice this means that a special exception, :exc:`ExceptionGroup` (or
:exc:`BaseExceptionGroup`) is raised which contains both exception objects.

To catch such exceptions potentially nested in groups, special measures are required.
On Python 3.11 and later, you can use the ``except*`` syntax to catch multiple
exceptions::

    from anyio import create_task_group

    try:
        async with create_task_group() as tg:
            tg.start_soon(some_task)
            tg.start_soon(another_task)
    except* ValueError as excgroup:
        for exc in excgroup.exceptions:
            ...  # handle each ValueError
    except* KeyError as excgroup:
        for exc in excgroup.exceptions:
            ...  # handle each KeyError

If compatibility with older Python versions is required, you can use the ``catch()``
function from the exceptiongroup_ package::

    from anyio import create_task_group
    from exceptiongroup import catch

    def handle_valueerror(excgroup: ExceptionGroup) -> None:
        for exc in excgroup.exceptions:
            ...  # handle each ValueError

    def handle_keyerror(excgroup: ExceptionGroup) -> None:
        for exc in excgroup.exceptions:
            ...  # handle each KeyError

    with catch({
        ValueError: handle_valueerror,
        KeyError: handle_keyerror
    }):
        async with create_task_group() as tg:
            tg.start_soon(some_task)
            tg.start_soon(another_task)

If you need to set local variables in the handlers, declare them as ``nonlocal``::

    async def yourfunc():
        somevariable: str | None = None

        def handle_valueerror(exc):
            nonlocal somevariable
            somevariable = 'whatever'

        with catch({
            ValueError: handle_valueerror,
            KeyError: handle_keyerror
        }):
            async with create_task_group() as tg:
                tg.start_soon(some_task)
                tg.start_soon(another_task)

        print(f"{somevariable=}")

.. _exceptiongroup: https://pypi.org/project/exceptiongroup/

Context propagation
-------------------

Whenever a new task is spawned, `context`_ will be copied to the new task. It is
important to note *which* context will be copied to the newly spawned task. It is not
the context of the task group's host task that will be copied, but the context of the
task that calls :meth:`TaskGroup.start() <.abc.TaskGroup.start>` or
:meth:`TaskGroup.start_soon() <.abc.TaskGroup.start_soon>`.

.. _context: https://docs.python.org/3/library/contextvars.html

Differences with asyncio.TaskGroup
----------------------------------

The :class:`asyncio.TaskGroup` class, added in Python 3.11, is very similar in design to
the AnyIO :class:`~.abc.TaskGroup` class. The asyncio counterpart has some important
differences in its semantics, however:

* The task group itself is instantiated directly, rather than using a factory function
* Tasks are spawned solely through :meth:`~asyncio.TaskGroup.create_task`; there is no
  ``start()`` or ``start_soon()`` method
* The :meth:`~asyncio.TaskGroup.create_task` method returns a task object which can be
  awaited on (or cancelled)
* Tasks spawned via :meth:`~asyncio.TaskGroup.create_task` can only be cancelled
  individually (there is no ``cancel()`` method or similar in the task group)
* When a task spawned via :meth:`~asyncio.TaskGroup.create_task` is cancelled before its
  coroutine has started running, it will not get a chance to handle the cancellation
  exception
* :class:`asyncio.TaskGroup` does not allow starting new tasks after an exception in
  one of the tasks has triggered a shutdown of the task group
* Tasks spawned from :class:`asyncio.TaskGroup` use different cancellation semantics
  (see the notes on :ref:`asyncio cancellation semantics <asyncio cancellation>`)

Asyncio call graph introspection support
----------------------------------------

.. versionadded:: 4.12.0

Python 3.14 added support for `call graph introspection`_ on asyncio which lets various
tools display the tree of Tasks or Futures that are waiting for a specific Future. AnyIO
supports this mechanism in its own task groups by adding and removing the task's
"waiter" as appropriate, just like asyncio's own task group class does. Here's a small
demonstration::

    import asyncio

    from anyio import create_task_group


    async def foo(level=0):
        if level == 3:
            asyncio.print_call_graph(asyncio.current_task())
            return

        async with create_task_group() as tg:
            tg.start_soon(foo, level + 1, name=f"Nesting level {level + 1}")

    asyncio.run(foo())

This results in an output like:

.. code-block::

    * Task(name='Nesting level 3', id=0x7f94f01c43f0)
      + Call stack:
      |   File '/usr/lib64/python3.14/asyncio/graph.py', line 276, in print_call_graph()
      |   File '/tmp/foo.py', line 8, in async foo()
      + Awaited by:
        * Task(name='Nesting level 2', id=0x7f94f03334e0)
          + Call stack:
          |   File '/tmp/venv/lib64/python3.14/site-packages/anyio/_backends/_asyncio.py', line 755, in async TaskGroup.__aexit__()
          |   File '/tmp/foo.py', line 11, in async foo()
          + Awaited by:
            * Task(name='Nesting level 1', id=0x7f94f03172f0)
              + Call stack:
              |   File '/tmp/venv/lib64/python3.14/site-packages/anyio/_backends/_asyncio.py', line 755, in async TaskGroup.__aexit__()
              |   File '/tmp/foo.py', line 11, in async foo()
              + Awaited by:
                * Task(name='Task-1', id=0x7f94f0316f30)
                  + Call stack:
                  |   File '/tmp/venv/lib64/python3.14/site-packages/anyio/_backends/_asyncio.py', line 755, in async TaskGroup.__aexit__()
                  |   File '/tmp/foo.py', line 11, in async foo()

.. _call graph introspection: https://docs.python.org/3.14/library/asyncio-graph.html
