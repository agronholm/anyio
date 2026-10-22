Porting an asyncio library to AnyIO
==============================================

Porting to AnyIO is more than changing imports. AnyIO uses structured concurrency
and level cancellation, so first identify who owns each background task, how work
is passed between tasks, and how shutdown happens. A library should expose async
functions and leave the choice of backend to its caller.

Run the port on asyncio first, then test it on Trio to find remaining dependencies
on asyncio APIs. A dependency that calls asyncio directly still requires the
asyncio backend. See :doc:`basics` and :doc:`testing` for backend selection.

Give background tasks an owner
----------------------------------------------

Instead of starting an orphan task with ``asyncio.create_task()``, use an
:func:`anyio.create_task_group` context. Its children cannot outlive the context.
Normal exit waits for the children, while an exception in the context or a child
cancels the other children. A service that runs indefinitely needs an explicit
shutdown signal or cancellation before the group can exit.

Pass an async callable and its arguments to ``start_soon()``. Unlike
``asyncio.create_task(worker())``, it does not accept a coroutine object::

    import anyio


    async def worker(done: anyio.Event) -> None:
        await anyio.sleep(0)
        done.set()


    async def main() -> None:
        done = anyio.Event()
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(worker, done)
            await done.wait()

        assert done.is_set()


    anyio.run(main)

Use ``task_group.start()`` and ``task_status.started()`` when the caller must wait
for a service to initialize. See :doc:`tasks` for startup handshakes, task handles
and handling exception groups.

Replace queues with memory object streams
----------------------------------------------

:func:`anyio.create_memory_object_stream` returns separate send and receive ends
instead of one queue. Replace ``queue.put(item)`` with ``send.send(item)`` and
``queue.get()`` with ``receive.receive()``. Closing all send ends lets an
``async for`` loop over the receive end finish without a sentinel::

    import anyio


    async def main() -> None:
        send, receive = anyio.create_memory_object_stream[int](1)

        async def produce() -> None:
            async with send:
                for value in range(3):
                    await send.send(value)

        async with anyio.create_task_group() as task_group:
            task_group.start_soon(produce)
            async with receive:
                values = [value async for value in receive]

        assert values == [0, 1, 2]


    anyio.run(main)

Buffer sizes are not interchangeable: an ``asyncio.Queue(maxsize=0)`` is
unbounded, but an AnyIO memory object stream with buffer size 0 waits for a
receiver before sending. Choose a positive bound for buffered work, or
``math.inf`` if an unbounded buffer is genuinely needed.

When there are multiple producers, give each a send clone and close the original
send end too. Receivers finish only after every send clone has closed. Memory
streams have no ``task_done()`` or ``join()``. Use the task group to wait for
consumers to finish processing, or send acknowledgements on another stream if
completion must be tracked while the group is still running. See :doc:`streams`.

Replace transport callbacks with stream operations
----------------------------------------------------------

Prefer :func:`anyio.connect_tcp` and :func:`anyio.create_tcp_listener` to
``loop.create_connection()`` and ``asyncio.Protocol``. Put the protocol logic in
an async function which owns a stream, rather than ``data_received()`` and
``connection_lost()`` callbacks. A listener's ``serve()`` method runs a handler
for each connection. See :doc:`networking` for client and server examples.

Await ``stream.send(data)`` instead of calling ``transport.write(data)`` or
``writer.write(data)`` followed by ``writer.drain()``. Manage the stream with
``async with`` or await ``aclose()`` instead of pairing ``close()`` with
``wait_closed()``. Unlike ``StreamReader.read()``, ``stream.receive()`` raises
:exc:`anyio.EndOfStream` at EOF instead of returning ``b""``.

Neither TCP reads nor callbacks preserve message boundaries. If the protocol
needs ``readexactly()`` or ``readuntil()``, wrap the receive stream in
:class:`anyio.streams.buffered.BufferedByteReceiveStream` and use its
``receive_exactly()`` or ``receive_until()`` methods. The latter requires a
maximum buffer size. Keep transport-specific integrations on asyncio until they
can be rewritten against a backend-independent stream interface.

Replace reusable events with explicit state
----------------------------------------------------------

AnyIO events are one-shot notifications and have no ``clear()``. Create a new
:class:`anyio.Event` for each independent notification, but do not just replace
an event while existing waiters still hold the old object.

If the event represents a repeatedly changing state, use an
:class:`anyio.Condition` and test the state under its lock. For example, an
open/closed gate can be expressed without clearing notifications::

    import anyio


    class Gate:
        def __init__(self) -> None:
            self._open = False
            self._condition = anyio.Condition()

        async def set_open(self, value: bool) -> None:
            async with self._condition:
                self._open = value
                self._condition.notify_all()

        async def wait(self) -> None:
            async with self._condition:
                await self._condition.wait_for(lambda: self._open)


    async def main() -> None:
        gate = Gate()
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(gate.wait)
            await gate.set_open(True)

        await gate.set_open(False)
        async with anyio.create_task_group() as task_group:
            task_group.start_soon(gate.wait)
            await gate.set_open(True)


    anyio.run(main)

This waits for the gate to be open, not for every historical transition. If every
transition must be consumed, pass messages through an object stream instead.
See :doc:`synchronization` for events and conditions.

Audit cancellation, callbacks and thread boundaries
----------------------------------------------------------

AnyIO cancellation is level-triggered: an effectively cancelled scope can raise
at each yield point, rather than delivering a single ``asyncio.CancelledError``.
Replace ``asyncio.wait_for()`` with an enclosing :func:`anyio.fail_after` where
appropriate, and use :func:`anyio.get_cancelled_exc_class` when catching
cancellation. Re-raise it after cleanup and shield awaited cleanup that must
complete. See :doc:`cancellation` before porting code that suppresses cancellation.

Do not assume that asyncio futures, transports or callbacks become portable by
running them inside an AnyIO task. Prefer a task-group startup handshake, an
event plus shared result state, or an object stream for the operation's result.
Callbacks from another thread must enter the event-loop thread through the
interfaces described in :doc:`threads`, not access AnyIO primitives directly.
Test cancellation and shutdown as well as the successful path on both backends.
