Migrating from AnyIO 2 to AnyIO 3
=================================

.. py:currentmodule:: anyio

AnyIO 3 changed several previously asynchronous functions and methods into regular ones for two
reasons:

#. to better serve use cases where synchronous callbacks are used by third party libraries
#. to better match the API of trio_

The following functions and methods were changed:

* :func:`current_time`
* :func:`current_effective_deadline`
* :meth:`CancelScope.cancel() <.abc.CancelScope.cancel>`
* :meth:`CapacityLimiter.acquire_nowait() <.abc.CapacityLimiter.acquire_nowait>`
* :meth:`CapacityLimiter.acquire_on_behalf_of_nowait()
  <.abc.CapacityLimiter.acquire_on_behalf_of_nowait>`
* :meth:`Condition.release() <.abc.Condition.release>`
* :meth:`Event.set() <.abc.Event.set>`
* :func:`get_current_task`
* :func:`get_running_tasks`
* :meth:`Lock.release() <.abc.Lock.release>`
* :meth:`MemoryObjectReceiveStream.receive_nowait()
  <.streams.memory.MemoryObjectReceiveStream.receive_nowait>`
* :meth:`MemoryObjectSendStream.send_nowait() <.streams.memory.MemoryObjectSendStream.send_nowait>`
* :func:`open_signal_receiver`
* :meth:`Semaphore.release() <.abc.Semaphore.release>`
* :meth:`TaskGroup.spawn() <.abc.TaskGroup.spawn>`

When migrating to AnyIO 3, simply remove the ``await`` from each call to these.

The following async context managers changed to regular context managers:

* :func:`fail_after`
* :func:`move_on_after`
* :func:`open_cancel_scope`

When migrating, just change ``async with`` into a plain ``with``.

.. _trio: https://github.com/python-trio/trio

Writing libraries compatible with both 2.x and 3.x
--------------------------------------------------

When you're writing a library that needs to be compatible with both major releases, you will need
to use the compatibility functions added in AnyIO 2.2: :func:`maybe_async` and
:func:`maybe_async_cm`. These will let you safely use functions/methods and context managers
(respectively) regardless of which major release is currently installed.

Example 1 – setting an event::

    from anyio.abc import Event
    from anyio import maybe_async


    async def foo(event: Event):
        await maybe_async(event.set())
        ...

Example 2 – opening a cancel scope::

    from anyio import open_cancel_scope, maybe_async_cm

    async def foo():
        async with maybe_async_cm(open_cancel_scope()) as scope:
            ...
