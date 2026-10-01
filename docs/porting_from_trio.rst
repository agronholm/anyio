Porting a Trio library to AnyIO
========================================

AnyIO uses Trio's structured concurrency and cancellation model, so a Trio library
can often retain its task structure while replacing its I/O and synchronization
primitives. Using AnyIO throughout the library lets callers run it on either the
Trio or asyncio backend. Merely replacing ``trio.run()`` does not make calls to
Trio-specific APIs work on asyncio.

Start by running the port on the Trio backend, then test it on asyncio as well.
Applications can select a backend with ``anyio.run(main, backend="trio")``.
Libraries should expose async functions rather than choose an event loop for their
callers. See :doc:`basics` for running asynchronous code.

Task groups instead of nurseries
----------------------------------------

Replace ``trio.open_nursery()`` with :func:`anyio.create_task_group`. The task group
has ``start_soon()``, ``start()`` and ``cancel_scope``, like a Trio nursery.
Pass an async callable and its positional arguments to ``start_soon()`` or
``start()``, not an already created coroutine object.

For example, this Trio code::

    import trio


    async def worker(results: list[int], value: int) -> None:
        await trio.sleep(0)
        results.append(value)


    async def main() -> None:
        results: list[int] = []
        async with trio.open_nursery() as nursery:
            nursery.start_soon(worker, results, 1)
            nursery.start_soon(worker, results, 2)

        assert sorted(results) == [1, 2]


    trio.run(main)

becomes::

    import anyio


    async def worker(results: list[int], value: int) -> None:
        await anyio.sleep(0)
        results.append(value)


    async def main() -> None:
        results: list[int] = []
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(worker, results, 1)
            task_group.start_soon(worker, results, 2)

        assert sorted(results) == [1, 2]


    anyio.run(main)

When a child reports readiness to ``start()``, replace ``trio.TASK_STATUS_IGNORED``
with ``anyio.TASK_STATUS_IGNORED`` and annotate the parameter with
:class:`anyio.abc.TaskStatus`. Keep the call to ``task_status.started()``.
See :doc:`tasks` for startup handshakes and handling exception groups.

Channels and byte streams
----------------------------------------

Replace ``trio.open_memory_channel[T](buffer_size)`` with
``anyio.create_memory_object_stream[T](buffer_size)``. Both return separate send
and receive objects. A zero-sized buffer waits for a receiver before sending.
Keep the streams' context managers and close every send clone so receivers can
finish iterating once the producers are done::

    import anyio


    async def main() -> None:
        send, receive = anyio.create_memory_object_stream[int](0)

        async def produce() -> None:
            async with send:
                await send.send(1)
                await send.send(2)

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(produce)
            async with receive:
                values = [value async for value in receive]

        assert values == [1, 2]


    anyio.run(main)

For byte streams, replace ``send_all()`` with ``send()`` and ``receive_some()``
with ``receive()``. AnyIO byte streams raise :exc:`anyio.EndOfStream` at EOF
instead of returning an empty byte string. Update read loops accordingly, or use
async iteration over the receive stream. See :doc:`streams` and :doc:`networking`
for the corresponding interfaces and socket factories.

Cancellation and other backend-specific APIs
------------------------------------------------------------

Use :class:`anyio.CancelScope`, :func:`anyio.move_on_after` and
:func:`anyio.fail_after` in place of their Trio equivalents. Cancel scopes remain
synchronous context managers, even inside async functions. Replace catches of
``trio.Cancelled`` with ``except anyio.get_cancelled_exc_class():`` and always
re-raise the cancellation exception after cleanup. Awaited cleanup in a cancelled
scope needs a shielded cancel scope. See :doc:`cancellation`.

Replace Trio locks, events and semaphores with the corresponding AnyIO classes.
Use :func:`anyio.to_thread.run_sync` for blocking calls and consult :doc:`threads`
before porting calls back from worker threads. Arguments and keyword options are
not necessarily identical between the libraries.

Audit dependencies and uses of ``trio.lowlevel``, ``trio.socket`` and
``trio.testing`` separately. AnyIO does not provide a replacement for every Trio
API, and a dependency that calls Trio directly still requires the Trio backend.
Do not treat changing imports alone as proof of backend independence.

For the port's test suite, replace Trio-specific test markers with
``pytest.mark.anyio`` and use the ``anyio_backend`` fixture to select the backends.
Run the tests on both asyncio and Trio, including cancellation, stream closure and
error handling. See :doc:`testing` for fixture configuration and the limitations
of backend-specific testing utilities.
