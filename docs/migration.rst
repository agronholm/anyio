Migrating from AnyIO 2 to AnyIO 3
=================================

.. py:currentmodule:: anyio

AnyIO 3 changed some functions and methods in a way that needs some adaptation in your code.
All deprecated functions and methods will be removed in AnyIO 4.

Asynchronous functions converted to synchronous
-----------------------------------------------

AnyIO 3 changed several previously asynchronous functions and methods into regular ones for two
reasons:

#. to better serve use cases where synchronous callbacks are used by third party libraries
#. to better match the API of trio_

The following functions and methods were changed:

* :func:`current_time`
* :func:`current_effective_deadline`
* :meth:`CancelScope.cancel() <.CancelScope.cancel>`
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

When migrating to AnyIO 3, simply remove the ``await`` from each call to these.

.. note:: For backwards compatibility reasons, :func:`current_time`,
          :func:`current_effective_deadline` and :func:`get_running_tasks` return objects which are
          awaitable versions of their original types (:class:`float` and :class:`list`,
          respectively). These awaitable versions are subclasses of the original types so they
          should behave as their originals, but if you absolutely need the pristine original types,
          you can either use ``maybe_async`` or ``float()`` / ``list()`` on the returned
          value as appropriate.

The following async context managers changed to regular context managers:

* :func:`fail_after`
* :func:`move_on_after`
* ``open_cancel_scope()`` (now just ``CancelScope()``)

When migrating, just change ``async with`` into a plain ``with``.

With the exception of
:meth:`MemoryObjectReceiveStream.receive_nowait() <.streams.memory.MemoryObjectReceiveStream.receive_nowait>`,
all of them can still be used like before – they will raise :exc:`DeprecationWarning` when used
this way on AnyIO 3, however.

If you're writing a library that needs to be compatible with both major releases, you will need
to use the compatibility functions added in AnyIO 2.2: ``maybe_async()`` and
``maybe_async_cm()``. These will let you safely use functions/methods and context managers
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

Starting tasks
--------------

The ``TaskGroup.spawn()`` coroutine method has been deprecated in favor of the synchronous
method :meth:`.TaskGroup.start_soon` (which mirrors ``start_soon()`` in trio's nurseries).
If you're fully migrating to AnyIO 3, simply switch to calling the new method (and remove the ``await``).

If your code needs to work with both AnyIO 2 and 3, you can keep using ``TaskGroup.spawn()``
(until AnyIO 4) and suppress the deprecation warning::

    import warnings

    async def foo():
        async with create_task_group() as tg:
            with warnings.catch_warnings():
                await tg.spawn(otherfunc)

Blocking portal changes
-----------------------

AnyIO now **requires** :func:`.from_thread.start_blocking_portal` to be used as a context manager::

    from anyio import sleep
    from anyio.from_thread import start_blocking_portal

    with start_blocking_portal() as portal:
        portal.call(sleep, 1)

As with ``TaskGroup.spawn()``, the ``BlockingPortal.spawn_task()`` method has also been renamed
to :meth:`~from_thread.BlockingPortal.start_task_soon`, so as to be consistent with task groups.

The ``create_blocking_portal()`` factory function was also deprecated in favor of instantiating
:class:`~from_thread.BlockingPortal` directly.

For code requiring cross compatibility, catching the deprecation warning (as above) should work.

Synchronization primitives
--------------------------

Synchronization primitive factories (``create_event()`` etc.) were deprecated in favor of
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

Threading functions moved
-------------------------

Threading functions were restructured to submodules, following the example of trio:

* ``current_default_worker_thread_limiter`` → :func:`.to_thread.current_default_thread_limiter`
  (NOTE: the function was renamed too!)
* ``run_sync_in_worker_thread()`` → :func:`.to_thread.run_sync`
* ``run_async_from_thread()`` → :func:`.from_thread.run`
* ``run_sync_from_thread()`` → :func:`.from_thread.run_sync`

The old versions are still in place but emit deprecation warnings when called.
