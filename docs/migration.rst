Migrating from AnyIO 2 to AnyIO 3
=================================

.. py:currentmodule:: anyio

AnyIO 3 changed some functions and methods in a way that needs some adaptation in your code.

Asynchronous functions converted to synchronous
-----------------------------------------------

AnyIO 3 changed several previously asynchronous functions and methods into regular ones for two
reasons:

#. to better serve use cases where synchronous callbacks are used by third party libraries
#. to better match the API of trio_

The following functions and methods were changed:

* :func:`current_time`
* :func:`current_effective_deadline`
* :meth:`CancelScope.cancel() <.abc.CancelScope.cancel>`
* :meth:`CapacityLimiter.acquire_nowait`
* :meth:`CapacityLimiter.acquire_on_behalf_of_nowait`
* :meth:`Condition.release`
* :meth:`Event.set`
* :func:`get_current_task`
* :func:`get_running_tasks`
* :meth:`Lock.release`
* :meth:`MemoryObjectReceiveStream.receive_nowait()
  <.streams.memory.MemoryObjectReceiveStream.receive_nowait>`
* :meth:`MemoryObjectSendStream.send_nowait() <.streams.memory.MemoryObjectSendStream.send_nowait>`
* :func:`open_signal_receiver`
* :meth:`Semaphore.release`
* :meth:`TaskGroup.spawn() <.abc.TaskGroup.spawn>`

When migrating to AnyIO 3, simply remove the ``await`` from each call to these.

The following async context managers changed to regular context managers:

* :func:`fail_after`
* :func:`move_on_after`
* :func:`open_cancel_scope`

When migrating, just change ``async with`` into a plain ``with``.

With the exception of
:meth:`MemoryObjectReceiveStream.receive_nowait() <.streams.memory.MemoryObjectReceiveStream.receive_nowait>`,
all of them can still be used like before – they will raise :exc:`DeprecationWarning` when used
this way on AnyIO 3, however.

If you're writing a library that needs to be compatible with both major releases, you will need
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

    from anyio import CancelScope, maybe_async_cm

    async def foo():
        async with maybe_async_cm(CancelScope()) as scope:
            ...

.. _trio: https://github.com/python-trio/trio

Synchronization primitives
--------------------------

Synchronization primitive factories (:func:`create_event` etc.) were deprecated in favor of
instantiating the classes directly. So convert code like this::

    from anyio import create_event

    async def main():
        event = create_event()

into this::

    from anyio import Event

    async def main():
        event = Event()

or, if you need to work with both AnyIO 2 and 3::

    try:
        from anyio import Event
        create_event = Event
    except ImportError:
        from anyio import create_event
        from anyio.abc import Event

    async def foo() -> Event:
        return create_event()
