Porting a Trio library to AnyIO
========================================

AnyIO uses Trio's structured concurrency and cancellation model. Most high-level
Trio APIs have direct counterparts, but a library is backend-independent only
when its dependencies and low-level integrations are backend-independent too.
Start the port on Trio, then test it on asyncio to find remaining Trio-only calls.

API counterparts
----------------------------------------

The following table covers common APIs used by Trio libraries. Entries with
different interfaces or semantics are discussed below, so these are not all
drop-in replacements.

.. list-table::
   :header-rows: 1
   :widths: 45 55

   * - Trio
     - AnyIO
   * - ``trio.run()``
     - ``anyio.run(..., backend="trio")`` (asyncio is the default)
   * - ``trio.open_nursery()`` / ``trio.Nursery``
     - :func:`anyio.create_task_group` / :class:`anyio.abc.TaskGroup`
   * - ``trio.TaskStatus`` / ``trio.TASK_STATUS_IGNORED``
     - :class:`anyio.abc.TaskStatus` / ``anyio.TASK_STATUS_IGNORED``
   * - ``trio.CancelScope`` / ``trio.Cancelled``
     - :class:`anyio.CancelScope` / :func:`anyio.get_cancelled_exc_class`
   * - ``trio.move_on_after()`` / ``trio.fail_after()``
     - :func:`anyio.move_on_after` / :func:`anyio.fail_after`
   * - ``trio.move_on_at()`` / ``trio.fail_at()``
     - :func:`anyio.move_on_at` / :func:`anyio.fail_at`
   * - ``trio.current_time()`` / ``trio.current_effective_deadline()``
     - :func:`anyio.current_time` / :func:`anyio.current_effective_deadline`
   * - ``trio.sleep()`` / ``trio.sleep_until()`` / ``trio.sleep_forever()``
     - :func:`anyio.sleep` / :func:`anyio.sleep_until` / :func:`anyio.sleep_forever`
   * - ``trio.Event`` / ``trio.Lock`` / ``trio.Condition``
     - :class:`anyio.Event` / :class:`anyio.Lock` / :class:`anyio.Condition`
   * - ``trio.Semaphore`` / ``trio.CapacityLimiter``
     - :class:`anyio.Semaphore` / :class:`anyio.CapacityLimiter`
   * - ``trio.open_memory_channel[T]()``
     - ``anyio.create_memory_object_stream[T]()``
   * - ``trio.MemorySendChannel`` / ``trio.MemoryReceiveChannel``
     - :class:`anyio.streams.memory.MemoryObjectSendStream` /
       :class:`anyio.streams.memory.MemoryObjectReceiveStream`
   * - ``trio.abc.SendStream`` / ``trio.abc.ReceiveStream``
     - :class:`anyio.abc.ByteSendStream` / :class:`anyio.abc.ByteReceiveStream`
   * - ``trio.abc.Stream`` / ``trio.SocketStream``
     - :class:`anyio.abc.ByteStream` / :class:`anyio.abc.SocketStream`
   * - ``trio.open_tcp_stream()`` / ``trio.open_unix_socket()``
     - :func:`anyio.connect_tcp` / :func:`anyio.connect_unix`
   * - ``trio.open_tcp_listeners()`` / ``trio.serve_tcp()``
     - :func:`anyio.create_tcp_listener` followed by ``listener.serve()``
   * - ``trio.SSLStream`` / ``trio.open_ssl_over_tcp_stream()``
     - :class:`anyio.streams.tls.TLSStream` / ``anyio.connect_tcp(..., tls=True)``
   * - ``trio.open_file()`` / ``trio.Path``
     - :func:`anyio.open_file` / :class:`anyio.Path`
   * - ``trio.run_process()``
     - :func:`anyio.run_process` (see :doc:`subprocesses` for process handles)
   * - ``trio.open_signal_receiver()``
     - :func:`anyio.open_signal_receiver`
   * - ``trio.to_thread.run_sync()``
     - :func:`anyio.to_thread.run_sync`
   * - ``trio.from_thread.run()`` / ``trio.from_thread.run_sync()``
     - :func:`anyio.from_thread.run` / :func:`anyio.from_thread.run_sync`
   * - ``trio.lowlevel.checkpoint()`` / ``checkpoint_if_cancelled()`` /
       ``cancel_shielded_checkpoint()``
     - The corresponding functions in ``anyio.lowlevel``
   * - ``trio.BrokenResourceError`` / ``trio.ClosedResourceError`` /
       ``trio.WouldBlock``
     - :exc:`anyio.BrokenResourceError` / :exc:`anyio.ClosedResourceError` /
       :exc:`anyio.WouldBlock`

Nurseries and memory channels retain their familiar context-manager and cloning
patterns. Task groups have ``start_soon()``, ``start()`` and ``cancel_scope``, and
memory object streams close their receive iteration after all send clones close.
See :doc:`tasks`, :doc:`streams` and :doc:`cancellation` for details.

Byte stream semantics
----------------------------------------

Rename ``send_all()`` to ``send()`` and ``receive_some()`` to ``receive()``.
The significant difference is EOF: Trio returns ``b""``, whereas AnyIO raises
:exc:`anyio.EndOfStream`. Change loops which check for an empty read, or use async
iteration to handle EOF automatically::

    from anyio.abc import ByteReceiveStream


    async def read_all(stream: ByteReceiveStream) -> bytes:
        chunks = []
        async for chunk in stream:
            chunks.append(chunk)

        return b"".join(chunks)

An AnyIO listener is an object with ``serve()`` and ``aclose()``, not a list of
Trio socket listeners. Acquire it with ``create_tcp_listener()`` and manage it
with ``async with``. A stream's socket information is exposed through typed
attributes, rather than Trio's ``stream.socket``. See :doc:`networking` and
:doc:`typedattrs`.

Function signatures can differ too. Compare keyword options for TLS, subprocess
and thread calls instead of renaming them blindly. Calls from external threads
need an AnyIO event-loop token, not a Trio token. See :doc:`threads` before
porting those calls.

Missing Trio functionality
----------------------------------------

AnyIO does not reproduce all of ``trio.socket``, ``trio.lowlevel`` or
``trio.testing``. Choose a migration strategy for each dependency:

* Replace direct ``trio.socket`` calls with AnyIO's socket factories and stream
  interfaces. If an integration must retain a raw nonblocking socket, consider
  :func:`anyio.wait_readable` and :func:`anyio.wait_writable`, and account for
  platform limitations rather than assuming Trio's socket wrapper is portable.
* Replace ``trio.lowlevel.spawn_system_task()`` with a task group owned by the
  component using the background task. Pass that group in or keep it open for
  the component's lifetime, and define how shutdown cancels its children.
  There is no backend-independent system-task lifetime to substitute directly.
* Keep guest-mode integration, Trio instruments and scheduler-specific code in
  a Trio-only adapter when there is no AnyIO counterpart. Restrict callers to
  the Trio backend until that adapter can be redesigned for other backends.
* Replace Trio-specific test streams with a small implementation of the AnyIO
  stream interfaces, or an in-process object stream when testing object-level
  behavior. Do not assume a Trio test stream has AnyIO's byte-stream EOF API.

Likewise, a dependency which still calls Trio directly remains Trio-only even
when the surrounding code uses AnyIO. Make that backend restriction explicit.

Migrating from pytest-trio
----------------------------------------

Replace ``pytest.mark.trio`` with ``pytest.mark.anyio``, or replace ``trio_mode``
with ``anyio_mode = "auto"``. Do not let both plugins try to run the same test.
The AnyIO plugin is bundled with AnyIO and defaults to parametrizing tests over
asyncio and Trio. Install Trio when testing that backend. To keep a test suite
Trio-only during the port, override ``anyio_backend`` to return ``"trio"``.
See :doc:`backend configuration <testing>` for fixture configuration and options.

The plugins also differ in fixture behavior:

* pytest-trio runs independent async fixtures concurrently. AnyIO runs async
  fixture setup, tests and teardown in the same task, serially. Do not rely on
  independent fixtures making progress concurrently during setup. Instead,
  start cooperating services in one task group and yield after they are ready.
* That same-task execution means context variables set by an async fixture are
  visible to the async test and teardown within the runner. It also allows an
  AnyIO task group or cancel scope to span an async fixture's ``yield``.
* pytest-trio's ``nursery`` fixture automatically cancels its children at
  teardown. AnyIO supplies no equivalent fixture. Open your own task group and
  explicitly cancel long-running children before leaving it.
* pytest-trio supports only function-scoped async fixtures. AnyIO can use
  higher-scoped async fixtures when their ``anyio_backend`` fixture has a
  compatible scope. Such fixtures keep the test runner alive across tests, so
  review shared state and context variables instead of assuming a fresh runner.

For example, a replacement for a background nursery fixture can be written as::

    import anyio
    import pytest


    @pytest.fixture
    async def background_group(anyio_backend):
        async with anyio.create_task_group() as group:
            yield group
            group.cancel_scope.cancel()


    @pytest.mark.anyio
    async def test_background_task(background_group):
        started = anyio.Event()

        async def worker():
            started.set()
            await anyio.sleep_forever()

        background_group.start_soon(worker)
        await started.wait()

Trio's ``mock_clock`` / ``autojump_clock`` and other pytest-trio utility fixtures
are not provided by AnyIO. Keep tests requiring these utilities in a separate
pytest-trio suite, or configure a Trio-only ``anyio_backend`` with a
``trio.testing.MockClock`` in its ``clock`` option. For backend-independent tests,
prefer explicit startup signals and events to assertions about scheduler timing.
See :doc:`testing` for runner lifetime and context-variable propagation, and the
`pytest-trio reference <https://pytest-trio.readthedocs.io/en/stable/reference.html>`_
for the plugin being replaced.
