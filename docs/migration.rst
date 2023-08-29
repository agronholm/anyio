Migrating from AnyIO 3 to AnyIO 4
=================================

.. py:currentmodule:: anyio

The non-standard exception group class was removed
--------------------------------------------------

AnyIO 3 had its own ``ExceptionGroup`` class which predated the :pep:`654` exception
group classes. This class has now been removed in favor of the built-in
:exc:`BaseExceptionGroup` and :exc:`ExceptionGroup` classes. If your code was either
raising the old ``ExceptionGroup`` exception or catching it, you need to make the switch
to these standard classes. Otherwise you can ignore this part.

If you're targeting Python releases older than 3.11, you need to use the exceptiongroup_
backport and import one of those classes from ``exceptiongroup``. The only difference
between :exc:`BaseExceptionGroup` and :exc:`ExceptionGroup` is that the latter can
only contain exceptions derived from :exc:`Exception`, and likewise can be caught with
``except Exception:``.

Task groups now wrap single exceptions in groups
------------------------------------------------

The most prominent backwards incompatible change in AnyIO 4 was that task groups now
always raise exception groups when either the host task or any child tasks raise an
exception (other than a cancellation exception). Previously, an exception group was only
raised when more than one exception needed to be raised from the task group. The
practical consequence is that if your code previously expected to catch a specific kind
of exception falling out of a task group, you now need to either switch to the
``except*`` syntax (if you're fortunate enough to work solely with Python 3.11 or
later), or use the ``catch()`` context manager from the exceptiongroup_ backport.

So, if you had code like this::

    try:
        await function_using_a_taskgroup()
    except ValueError as exc:
        ...

The Python 3.11+ equivalent would look almost the same::

    try:
        await function_using_a_taskgroup()
    except* ValueError as excgrp:
        # Note: excgrp is an ExceptionGroup now!
        ...

If you need to stay compatible with older Python releases, you need to use the
backport::

    from exceptiongroup import ExceptionGroup, catch

    def handle_value_errors(excgrp: ExceptionGroup) -> None:
        ...

    with catch({ValueError: handle_value_errors}):
        await function_using_a_taskgroup()

This difference often comes up in test suites too. For example, if you had this before
in a pytest-based test suite::

    with pytest.raises(ValueError):
        await function_using_a_taskgroup()

You now need to change it to::

    from exceptiongroup import ExceptionGroup

    with pytest.raises(ExceptionGroup) as exc:
        await function_using_a_taskgroup()

    assert len(exc.value.exceptions) == 1
    assert isinstance(exc.value.exceptions[0], ValueError)

If you need to stay compatible with both AnyIO 3 and 4, you can use the following
compatibility code to "collapse" single-exception groups by unwrapping them::

    import sys
    from contextlib import contextmanager
    from typing import Generator

    has_exceptiongroups = True
    if sys.version_info < (3, 11):
        try:
            from exceptiongroup import BaseExceptionGroup
        except ImportError:
            has_exceptiongroups = False


    @contextmanager
    def collapse_excgroups() -> Generator[None, None, None]:
        try:
            yield
        except BaseException as exc:
            if has_exceptiongroups:
                while isinstance(exc, BaseExceptionGroup) and len(exc.exceptions) == 1:
                    exc = exc.exceptions[0]

            raise exc

Syntax for type annotated memory object streams has changed
-----------------------------------------------------------

Where previously, creating type annotated memory object streams worked by passing the
desired type as the second argument::

    send, receive = create_memory_object_stream(100, int)

In 4.0, :class:`create_memory_object_stream() <create_memory_object_stream>` is a class
masquerading as a function, so you need to parametrize it::

    send, receive = create_memory_object_stream[int](100)

If you didn't parametrize your memory object streams before, then you don't need to make
any changes in this regard.

Event loop factories instead of event loop policies
----------------------------------------------------

If you're using a custom asyncio event loop policy with :func:`run`, you need to switch
to passing an *event loop factory*, that is, a callable that returns a new event loop.

Using uvloop_ as an example, code like the following::

    anyio.run(main, backend_options={"event_loop_policy": uvloop.EventLoopPolicy()})

should be converted into::

    anyio.run(main, backend_options={"loop_factory": uvloop.new_event_loop})

Make sure not to actually call the factory function!

.. _exceptiongroup: https://pypi.org/project/exceptiongroup/
.. _uvloop: https://github.com/MagicStack/uvloop

Migrating from AnyIO 2 to AnyIO 3
=================================

AnyIO 3 changed some functions and methods in a way that needs some adaptation in your
code. All deprecated functions and methods will be removed in AnyIO 4.

Asynchronous functions converted to synchronous
-----------------------------------------------

AnyIO 3 changed several previously asynchronous functions and methods into regular ones
for two reasons:

#. to better serve use cases where synchronous callbacks are used by third party
   libraries
#. to better match the API of Trio_

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
* :meth:`MemoryObjectSendStream.send_nowait()
  <.streams.memory.MemoryObjectSendStream.send_nowait>`
* :func:`open_signal_receiver`
* :meth:`Semaphore.release`

When migrating to AnyIO 3, simply remove the ``await`` from each call to these.

.. note:: For backwards compatibility reasons, :func:`current_time`,
   :func:`current_effective_deadline` and :func:`get_running_tasks` return objects which
   are awaitable versions of their original types (:class:`float` and :class:`list`,
   respectively). These awaitable versions are subclasses of the original types so they
   should behave as their originals, but if you absolutely need the pristine original
   types, you can either use ``maybe_async`` or ``float()`` / ``list()`` on the returned
   value as appropriate.

The following async context managers changed to regular context managers:

* :func:`fail_after`
* :func:`move_on_after`
* ``open_cancel_scope()`` (now just ``CancelScope()``)

When migrating, just change ``async with`` into a plain ``with``.

With the exception of
:meth:`MemoryObjectReceiveStream.receive_nowait()
<.streams.memory.MemoryObjectReceiveStream.receive_nowait>`,
all of them can still be used like before – they will raise :exc:`DeprecationWarning`
when used this way on AnyIO 3, however.

If you're writing a library that needs to be compatible with both major releases, you
will need to use the compatibility functions added in AnyIO 2.2: ``maybe_async()`` and
``maybe_async_cm()``. These will let you safely use functions/methods and context
managers (respectively) regardless of which major release is currently installed.

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

.. _Trio: https://github.com/python-trio/trio

Starting tasks
--------------

The ``TaskGroup.spawn()`` coroutine method has been deprecated in favor of the
synchronous method :meth:`.TaskGroup.start_soon` (which mirrors ``start_soon()`` in
Trio's nurseries). If you're fully migrating to AnyIO 3, simply switch to calling the
new method (and remove the ``await``).

If your code needs to work with both AnyIO 2 and 3, you can keep using
``TaskGroup.spawn()`` (until AnyIO 4) and suppress the deprecation warning::

    import warnings

    async def foo():
        async with create_task_group() as tg:
            with warnings.catch_warnings():
                await tg.spawn(otherfunc)

Blocking portal changes
-----------------------

AnyIO now **requires** :func:`.from_thread.start_blocking_portal` to be used as a
context manager::

    from anyio import sleep
    from anyio.from_thread import start_blocking_portal

    with start_blocking_portal() as portal:
        portal.call(sleep, 1)

As with ``TaskGroup.spawn()``, the ``BlockingPortal.spawn_task()`` method has also been
renamed to :meth:`~from_thread.BlockingPortal.start_task_soon`, so as to be consistent
with task groups.

The ``create_blocking_portal()`` factory function was also deprecated in favor of
instantiating :class:`~from_thread.BlockingPortal` directly.

For code requiring cross compatibility, catching the deprecation warning (as above)
should work.

Synchronization primitives
--------------------------

Synchronization primitive factories (``create_event()`` etc.) were deprecated in favor
of instantiating the classes directly. So convert code like this::

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

Threading functions were restructured to submodules, following the example of Trio:

* ``current_default_worker_thread_limiter`` →
  :func:`.to_thread.current_default_thread_limiter`
  (NOTE: the function was renamed too!)
* ``run_sync_in_worker_thread()`` → :func:`.to_thread.run_sync`
* ``run_async_from_thread()`` → :func:`.from_thread.run`
* ``run_sync_from_thread()`` → :func:`.from_thread.run_sync`

The old versions are still in place but emit deprecation warnings when called.
