Version history
===============

This library adheres to `Semantic Versioning 2.0 <http://semver.org/>`_.

**4.4.0**

- Added the ``BlockingPortalProvider`` class to aid with constructing synchronous
  counterparts to asynchronous interfaces that would otherwise require multiple blocking
  portals
- Added ``__slots__`` to ``AsyncResource`` so that child classes can use ``__slots__``
  (`#733 <https://github.com/agronholm/anyio/pull/733>`_; PR by Justin Su)
- Added the ``TaskInfo.has_pending_cancellation()`` method
- Fixed erroneous ``RuntimeError: called 'started' twice on the same task status``
  when cancelling a task in a TaskGroup created with the ``start()`` method before
  the first checkpoint is reached after calling ``task_status.started()``
  (`#706 <https://github.com/agronholm/anyio/issues/706>`_; PR by Dominik Schwabe)
- Fixed two bugs with ``TaskGroup.start()`` on asyncio:

  * Fixed erroneous ``RuntimeError: called 'started' twice on the same task status``
    when cancelling a task in a TaskGroup created with the ``start()`` method before
    the first checkpoint is reached after calling ``task_status.started()``
    (`#706 <https://github.com/agronholm/anyio/issues/706>`_; PR by Dominik Schwabe)
  * Fixed the entire task group being cancelled if a ``TaskGroup.start()`` call gets
    cancelled (`#685 <https://github.com/agronholm/anyio/issues/685>`_,
    `#710 <https://github.com/agronholm/anyio/issues/710>`_)
- Fixed a race condition that caused crashes when multiple event loops of the same
  backend were running in separate threads and simultaneously attempted to use AnyIO for
  their first time (`#425 <https://github.com/agronholm/anyio/issues/425>`_; PR by David
  Jiricek and Ganden Schaffner)
- Fixed cancellation delivery on asyncio incrementing the wrong cancel scope's
  cancellation counter when cascading a cancel operation to a child scope, thus failing
  to uncancel the host task (`#716 <https://github.com/agronholm/anyio/issues/716>`_)
- Fixed erroneous ``TypedAttributeLookupError`` if a typed attribute getter raises
  ``KeyError``
- Fixed the asyncio backend not respecting the ``PYTHONASYNCIODEBUG`` environment
  variable when setting the ``debug`` flag in ``anyio.run()``
- Fixed ``SocketStream.receive()`` not detecting EOF on asyncio if there is also data in
  the read buffer (`#701 <https://github.com/agronholm/anyio/issues/701>`_)
- Fixed ``MemoryObjectStream`` dropping an item if the item is delivered to a recipient
  that is waiting to receive an item but has a cancellation pending
  (`#728 <https://github.com/agronholm/anyio/issues/728>`_)
- Emit a ``ResourceWarning`` for ``MemoryObjectReceiveStream`` and
  ``MemoryObjectSendStream`` that were garbage collected without being closed (PR by
  Andrey Kazantcev)
- Fixed ``MemoryObjectSendStream.send()`` not raising ``BrokenResourceError`` when the
  last corresponding ``MemoryObjectReceiveStream`` is closed while waiting to send a
  falsey item (`#731 <https://github.com/agronholm/anyio/issues/731>`_; PR by Ganden
  Schaffner)

**4.3.0**

- Added support for the Python 3.12 ``walk_up`` keyword argument in
  ``anyio.Path.relative_to()`` (PR by Colin Taylor)
- Fixed passing ``total_tokens`` to ``anyio.CapacityLimiter()`` as a keyword argument
  not working on the ``trio`` backend
  (`#515 <https://github.com/agronholm/anyio/issues/515>`_)
- Fixed ``Process.aclose()`` not performing the minimum level of necessary cleanup when
  cancelled. Previously:

  - Cancellation of ``Process.aclose()`` could leak an orphan process
  - Cancellation of ``run_process()`` could very briefly leak an orphan process.
  - Cancellation of ``Process.aclose()`` or ``run_process()`` on Trio could leave
    standard streams unclosed

  (PR by Ganden Schaffner)
- Fixed ``Process.stdin.aclose()``, ``Process.stdout.aclose()``, and
  ``Process.stderr.aclose()`` not including a checkpoint on asyncio (PR by Ganden
  Schaffner)
- Fixed documentation on how to provide your own typed attributes

**4.2.0**

- Add support for ``byte``-based paths in ``connect_unix``, ``create_unix_listeners``,
  ``create_unix_datagram_socket``, and ``create_connected_unix_datagram_socket``. (PR by
  Lura Skye)
- Enabled the ``Event`` and ``CapacityLimiter`` classes to be instantiated outside an
  event loop thread
- Broadly improved/fixed the type annotations. Among other things, many functions and
  methods that take variadic positional arguments now make use of PEP 646
  ``TypeVarTuple`` to allow the positional arguments to be validated by static type
  checkers. These changes affected numerous methods and functions, including:

  * ``anyio.run()``
  * ``TaskGroup.start_soon()``
  * ``anyio.from_thread.run()``
  * ``anyio.from_thread.run_sync()``
  * ``anyio.to_thread.run_sync()``
  * ``anyio.to_process.run_sync()``
  * ``BlockingPortal.call()``
  * ``BlockingPortal.start_task_soon()``
  * ``BlockingPortal.start_task()``

  (also resolves `#560 <https://github.com/agronholm/anyio/issues/560>`_)
- Fixed various type annotations of ``anyio.Path`` to match Typeshed:

  * ``anyio.Path.__lt__()``
  * ``anyio.Path.__le__()``
  * ``anyio.Path.__gt__()``
  * ``anyio.Path.__ge__()``
  * ``anyio.Path.__truediv__()``
  * ``anyio.Path.__rtruediv__()``
  * ``anyio.Path.hardlink_to()``
  * ``anyio.Path.samefile()``
  * ``anyio.Path.symlink_to()``
  * ``anyio.Path.with_segments()``

  (PR by Ganden Schaffner)
- Fixed adjusting the total number of tokens in a ``CapacityLimiter`` on asyncio failing
  to wake up tasks waiting to acquire the limiter in certain edge cases (fixed with help
  from Egor Blagov)
- Fixed ``loop_factory`` and ``use_uvloop`` options not being used on the asyncio
  backend (`#643 <https://github.com/agronholm/anyio/issues/643>`_)
- Fixed cancellation propagating on asyncio from a task group to child tasks if the task
  hosting the task group is in a shielded cancel scope
  (`#642 <https://github.com/agronholm/anyio/issues/642>`_)

**4.1.0**

- Adapted to API changes made in Trio v0.23:

  - Call ``trio.to_thread.run_sync()`` using the ``abandon_on_cancel`` keyword argument
    instead of ``cancellable``
  - Removed a checkpoint when exiting a task group
  - Renamed the ``cancellable`` argument in ``anyio.to_thread.run_sync()`` to
    ``abandon_on_cancel`` (and deprecated the old parameter name)
  - Bumped minimum version of Trio to v0.23
- Added support for voluntary thread cancellation via
  ``anyio.from_thread.check_cancelled()``
- Bumped minimum version of trio to v0.23
- Exposed the ``ResourceGuard`` class in the public API
  (`#627 <https://github.com/agronholm/anyio/issues/627>`_)
- Fixed ``RuntimeError: Runner is closed`` when running higher-scoped async generator
  fixtures in some cases (`#619 <https://github.com/agronholm/anyio/issues/619>`_)
- Fixed discrepancy between ``asyncio`` and ``trio`` where reraising a cancellation
  exception in an ``except*`` block would incorrectly bubble out of its cancel scope
  (`#634 <https://github.com/agronholm/anyio/issues/634>`_)

**4.0.0**

- **BACKWARDS INCOMPATIBLE** Replaced AnyIO's own ``ExceptionGroup`` class with the PEP
  654 ``BaseExceptionGroup`` and ``ExceptionGroup``
- **BACKWARDS INCOMPATIBLE** Changes to cancellation semantics:

  - Any exceptions raising out of a task groups are now nested inside an
    ``ExceptionGroup`` (or ``BaseExceptionGroup`` if one or more ``BaseException`` were
    included)
  - Fixed task group not raising a cancellation exception on asyncio at exit if no child
    tasks were spawned and an outer cancellation scope had been cancelled before
  - Ensured that exiting a ``TaskGroup`` always hits a yield point, regardless of
    whether there are running child tasks to be waited on
  - On asyncio, cancel scopes will defer cancelling tasks that are scheduled to resume
    with a finished future
  - On asyncio and Python 3.9/3.10, cancel scopes now only suppress cancellation
    exceptions if the cancel message matches the scope
  - Task groups on all backends now raise a single cancellation exception when an outer
    cancel scope is cancelled, and no exceptions other than cancellation exceptions are
    raised in the group
- **BACKWARDS INCOMPATIBLE** Changes the pytest plugin to run all tests and fixtures in
  the same task, allowing fixtures to set context variables for tests and other fixtures
- **BACKWARDS INCOMPATIBLE** Changed ``anyio.Path.relative_to()`` and
  ``anyio.Path.is_relative_to()`` to only accept one argument, as passing multiple
  arguments is deprecated as of Python 3.12
- **BACKWARDS INCOMPATIBLE** Dropped support for spawning tasks from old-style coroutine
  functions (``@asyncio.coroutine``)
- **BACKWARDS INCOMPATIBLE** The ``policy`` option on the ``asyncio`` backend was
  changed to ``loop_factory`` to accommodate ``asyncio.Runner``
- Changed ``anyio.run()`` to use ``asyncio.Runner`` (or a back-ported version of it on
  Pythons older than 3.11) on the ``asyncio`` backend
- Dropped support for Python 3.7
- Added support for Python 3.12
- Bumped minimum version of trio to v0.22
- Added the ``anyio.Path.is_junction()`` and ``anyio.Path.walk()`` methods
- Added ``create_unix_datagram_socket`` and ``create_connected_unix_datagram_socket`` to
  create UNIX datagram sockets (PR by Jean Hominal)
- Fixed ``from_thread.run`` and ``from_thread.run_sync`` not setting sniffio on asyncio.
  As a result:

  - Fixed ``from_thread.run_sync`` failing when used to call sniffio-dependent functions
    on asyncio
  - Fixed ``from_thread.run`` failing when used to call sniffio-dependent functions on
    asyncio from a thread running trio or curio
  - Fixed deadlock when using ``from_thread.start_blocking_portal(backend="asyncio")``
    in a thread running trio or curio (PR by Ganden Schaffner)
- Improved type annotations:

  - The ``item_type`` argument of ``create_memory_object_stream`` was deprecated.
    To indicate the item type handled by the stream, use
    ``create_memory_object_stream[T_Item]()`` instead. Type checking should no longer
    fail when annotating memory object streams with uninstantiable item types (PR by
    Ganden Schaffner)
- Added the ``CancelScope.cancelled_caught`` property which tells users if the cancel
  scope suppressed a cancellation exception
- Fixed ``fail_after()`` raising an unwarranted ``TimeoutError`` when the cancel scope
  was cancelled before reaching its deadline
- Fixed ``MemoryObjectReceiveStream.receive()`` causing the receiving task on asyncio to
  remain in a cancelled state if the operation was cancelled after an item was queued to
  be received by the task (but before the task could actually receive the item)
- Fixed ``TaskGroup.start()`` on asyncio not responding to cancellation from the outside
- Fixed tasks started from ``BlockingPortal`` not notifying synchronous listeners
  (``concurrent.futures.wait()``) when they're cancelled
- Removed unnecessary extra waiting cycle in ``Event.wait()`` on asyncio in the case
  where the event was not yet set
- Fixed processes spawned by ``anyio.to_process()`` being "lost" as unusable to the
  process pool when processes that have idled over 5 minutes are pruned at part of the
  ``to_process.run_sync()`` call, leading to increased memory consumption
  (PR by Anael Gorfinkel)

Changes since 4.0.0rc1:

- Fixed the type annotation of ``TaskGroup.start_soon()`` to accept any awaitables
  (already in v3.7.0 but was missing from 4.0.0rc1)
- Changed ``CancelScope`` to also consider the cancellation count (in addition to the
  cancel message) on asyncio to determine if a cancellation exception should be
  swallowed on scope exit, to combat issues where third party libraries catch the
  ``CancelledError`` and raise another, thus erasing the original cancel message
- Worked around a `CPython bug <https://github.com/python/cpython/issues/108668>`_ that
  caused ``TLSListener.handle_handshake_error()`` on asyncio to log ``"NoneType: None"``
  instead of the error (PR by Ganden Schaffner)
- Re-added the ``item_type`` argument to ``create_memory_object_stream()`` (but using it
  raises a deprecation warning and does nothing with regards to the static types of the
  returned streams)
- Fixed processes spawned by ``anyio.to_process()`` being "lost" as unusable to the
  process pool when processes that have idled over 5 minutes are pruned at part of the
  ``to_process.run_sync()`` call, leading to increased memory consumption
  (PR by Anael Gorfinkel)

**3.7.1**

- Fixed sending large buffers via UNIX stream sockets on asyncio
- Fixed several minor documentation issues (broken links to classes, missing classes or
  attributes)

**3.7.0**

- Dropped support for Python 3.6
- Improved type annotations:

  - Several functions and methods that were previously annotated as accepting
    ``Coroutine[Any, Any, Any]`` as the return type of the callable have been amended to
    accept ``Awaitable[Any]`` instead, to allow a slightly broader set of coroutine-like
    inputs, like ``async_generator_asend`` objects returned from the ``asend()`` method
    of async generators, and to match the ``trio`` annotations:

    - ``anyio.run()``
    - ``anyio.from_thread.run()``
    - ``TaskGroup.start_soon()``
    - ``TaskGroup.start()``
    - ``BlockingPortal.call()``
    - ``BlockingPortal.start_task_soon()``
    - ``BlockingPortal.start_task()``

    Note that this change involved only changing the type annotations; run-time
    functionality was not altered.

  - The ``TaskStatus`` class is now a generic protocol, and should be parametrized to
    indicate the type of the value passed to ``task_status.started()``
  - The ``Listener`` class is now covariant in its stream type
  - ``create_memory_object_stream()`` now allows passing only ``item_type``
  - Object receive streams are now covariant and object send streams are correspondingly
    contravariant
- Changed ``TLSAttribute.shared_ciphers`` to match the documented semantics of
  ``SSLSocket.shared_ciphers`` of always returning ``None`` for client-side streams
- Fixed ``CapacityLimiter`` on the asyncio backend to order waiting tasks in the FIFO
  order (instead of LIFO) (PR by Conor Stevenson)
- Fixed ``CancelScope.cancel()`` not working on asyncio if called before entering the
  scope
- Fixed ``open_signal_receiver()`` inconsistently yielding integers instead of
  ``signal.Signals`` instances on the ``trio`` backend
- Fixed ``to_thread.run_sync()`` hanging on asyncio if the target callable raises
  ``StopIteration``
- Fixed ``start_blocking_portal()`` raising an unwarranted
  ``RuntimeError: This portal is not running`` if a task raises an exception that causes
  the event loop to be closed
- Fixed ``current_effective_deadline()`` not returning ``-inf`` on asyncio when the
  currently active cancel scope has been cancelled (PR by Ganden Schaffner)
- Fixed the ``OP_IGNORE_UNEXPECTED_EOF`` flag in an SSL context created by default in
  ``TLSStream.wrap()`` being inadvertently set on Python 3.11.3 and 3.10.11
- Fixed ``CancelScope`` to properly handle asyncio task uncancellation on Python 3.11
  (PR by Nikolay Bryskin)
- Fixed ``OSError`` when trying to use ``create_tcp_listener()`` to bind to a link-local
  IPv6 address (and worked around related bugs in ``uvloop``)
- Worked around a `PyPy bug <https://foss.heptapod.net/pypy/pypy/-/issues/3938>`_
  when using ``anyio.getaddrinfo()`` with for IPv6 link-local addresses containing
  interface names

**3.6.2**

- Pinned Trio to < 0.22 to avoid incompatibility with AnyIO's ``ExceptionGroup`` class
  causing ``AttributeError: 'NonBaseMultiError' object has no attribute '_exceptions'``

**3.6.1**

- Fixed exception handler in the asyncio test runner not properly handling a context
  that does not contain the ``exception`` key

**3.6.0**

- Fixed ``TypeError`` in ``get_current_task()`` on asyncio when using a custom ``Task``
  factory
- Updated type annotations on ``run_process()`` and ``open_process()``:

  * ``command`` now accepts accepts bytes and sequences of bytes
  * ``stdin``, ``stdout`` and ``stderr`` now accept file-like objects
    (PR by John T. Wodder II)
- Changed the pytest plugin to run both the setup and teardown phases of asynchronous
  generator fixtures within a single task to enable use cases such as cancel scopes and
  task groups where a context manager straddles the ``yield``

**3.5.0**

- Added ``start_new_session`` keyword argument to ``run_process()`` and
  ``open_process()`` (PR by Jordan Speicher)
- Fixed deadlock in synchronization primitives on asyncio which can happen if a task
  acquiring a primitive is hit with a native (not AnyIO) cancellation with just the
  right timing, leaving the next acquiring task waiting forever
  (`#398 <https://github.com/agronholm/anyio/issues/398>`_)
- Added workaround for bpo-46313_ to enable compatibility with OpenSSL 3.0

.. _bpo-46313: https://bugs.python.org/issue46313

**3.4.0**

- Added context propagation to/from worker threads in ``to_thread.run_sync()``,
  ``from_thread.run()`` and ``from_thread.run_sync()``
  (`#363 <https://github.com/agronholm/anyio/issues/363>`_; partially based on a PR by
  Sebastián Ramírez)

  **NOTE**: Requires Python 3.7 to work properly on asyncio!
- Fixed race condition in ``Lock`` and ``Semaphore`` classes when a task waiting on
  ``acquire()`` is cancelled while another task is waiting to acquire the same primitive
  (`#387 <https://github.com/agronholm/anyio/issues/387>`_)
- Fixed async context manager's ``__aexit__()`` method not being called in
  ``BlockingPortal.wrap_async_context_manager()`` if the host task is cancelled
  (`#381 <https://github.com/agronholm/anyio/issues/381>`_; PR by Jonathan Slenders)
- Fixed worker threads being marked as being event loop threads in sniffio
- Fixed task parent ID not getting set to the correct value on asyncio
- Enabled the test suite to run without IPv6 support, trio or pytest plugin autoloading

**3.3.4**

- Fixed ``BrokenResourceError`` instead of ``EndOfStream`` being raised in ``TLSStream``
  when the peer abruptly closes the connection while ``TLSStream`` is receiving data
  with ``standard_compatible=False`` set

**3.3.3**

- Fixed UNIX socket listener not setting accepted sockets to non-blocking mode on
  asyncio
- Changed unconnected UDP sockets to be always bound to a local port (on "any"
  interface) to avoid errors on asyncio + Windows

**3.3.2**

- Fixed cancellation problem on asyncio where level-triggered cancellation for **all**
  parent cancel scopes would not resume after exiting a shielded nested scope
  (`#370 <https://github.com/agronholm/anyio/issues/370>`_)

**3.3.1**

- Added missing documentation for the ``ExceptionGroup.exceptions`` attribute
- Changed the asyncio test runner not to use uvloop by default (to match the behavior of
  ``anyio.run()``)
- Fixed ``RuntimeError`` on asyncio when a ``CancelledError`` is raised from a task
  spawned through a ``BlockingPortal``
  (`#357 <https://github.com/agronholm/anyio/issues/357>`_)
- Fixed asyncio warning about a ``Future`` with an exception that was never retrieved
  which happened when a socket was already written to but the peer abruptly closed the
  connection

**3.3.0**

- Added asynchronous ``Path`` class
- Added the ``wrap_file()`` function for wrapping existing files as asynchronous file
  objects
- Relaxed the type of the ``path`` initializer argument to ``FileReadStream`` and
  ``FileWriteStream`` so they accept any path-like object (including the new
  asynchronous ``Path`` class)
- Dropped unnecessary dependency on the ``async_generator`` library
- Changed the generics in ``AsyncFile`` so that the methods correctly return either
  ``str`` or ``bytes`` based on the argument to ``open_file()``
- Fixed an asyncio bug where under certain circumstances, a stopping worker thread would
  still accept new assignments, leading to a hang

**3.2.1**

- Fixed idle thread pruning on asyncio sometimes causing an expired worker thread to be
  assigned a task

**3.2.0**

- Added Python 3.10 compatibility
- Added the ability to close memory object streams synchronously (including support for
  use as a synchronous context manager)
- Changed the default value of the ``use_uvloop`` asyncio backend option to ``False`` to
  prevent unsafe event loop policy changes in different threads
- Fixed ``to_thread.run_sync()`` hanging on the second call on asyncio when used with
  ``loop.run_until_complete()``
- Fixed ``to_thread.run_sync()`` prematurely marking a worker thread inactive when a
  task await on the result is cancelled
- Fixed ``ResourceWarning`` about an unclosed socket when UNIX socket connect fails on
  asyncio
- Fixed the type annotation of ``open_signal_receiver()`` as a synchronous context
  manager
- Fixed the type annotation of ``DeprecatedAwaitable(|List|Float).__await__`` to match
  the ``typing.Awaitable`` protocol

**3.1.0**

- Added ``env`` and ``cwd`` keyword arguments to ``run_process()`` and ``open_process``.
- Added support for mutation of ``CancelScope.shield`` (PR by John Belmonte)
- Added the ``sleep_forever()`` and ``sleep_until()`` functions
- Changed asyncio task groups so that if the host and child tasks have only raised
  ``CancelledErrors``, just one ``CancelledError`` will now be raised instead of an
  ``ExceptionGroup``, allowing asyncio to ignore it when it propagates out of the task
- Changed task names to be converted to ``str`` early on asyncio (PR by Thomas Grainger)
- Fixed ``sniffio._impl.AsyncLibraryNotFoundError: unknown async library, or not in
  async context`` on asyncio and Python 3.6 when ``to_thread.run_sync()`` is used from
  ``loop.run_until_complete()``
- Fixed odd ``ExceptionGroup: 0 exceptions were raised in the task group`` appearing
  under certain circumstances on asyncio
- Fixed ``wait_all_tasks_blocked()`` returning prematurely on asyncio when a previously
  blocked task is cancelled (PR by Thomas Grainger)
- Fixed declared return type of ``TaskGroup.start()`` (it was declared as ``None``, but
  anything can be returned from it)
- Fixed ``TextStream.extra_attributes`` raising ``AttributeError`` (PR by Thomas
  Grainger)
- Fixed ``await maybe_async(current_task())`` returning ``None`` (PR by Thomas Grainger)
- Fixed: ``pickle.dumps(current_task())`` now correctly raises ``TypeError`` instead of
  pickling to ``None`` (PR by Thomas Grainger)
- Fixed return type annotation of ``Event.wait()`` (``bool`` → ``None``) (PR by Thomas
  Grainger)
- Fixed return type annotation of ``RunVar.get()`` to return either the type of the
  default value or the type of the contained value (PR by Thomas Grainger)
- Fixed a deprecation warning message to refer to ``maybe_async()`` and not
  ``maybe_awaitable()`` (PR by Thomas Grainger)
- Filled in argument and return types for all functions and methods previously missing
  them (PR by Thomas Grainger)

**3.0.1**

- Fixed ``to_thread.run_sync()`` raising ``RuntimeError`` on asyncio when no "root" task
  could be found for setting up a cleanup callback. This was a problem at least on
  Tornado and possibly also Twisted in asyncio compatibility mode. The life of worker
  threads is now bound to the the host task of the topmost cancel scope hierarchy
  starting from the current one, or if no cancel scope is active, the current task.

**3.0.0**

- Curio support has been dropped (see the :doc:`FAQ <faq>` as for why)
- API changes:

  * **BACKWARDS INCOMPATIBLE** Submodules under ``anyio.abc.`` have been made private
    (use only ``anyio.abc`` from now on).
  * **BACKWARDS INCOMPATIBLE** The following method was previously a coroutine method
    and has been converted into a synchronous one:

    * ``MemoryObjectReceiveStream.receive_nowait()``

  * The following functions and methods are no longer asynchronous but can still be
    awaited on (doing so will emit a deprecation warning):

    * ``current_time()``
    * ``current_effective_deadline()``
    * ``get_current_task()``
    * ``get_running_tasks()``
    * ``CancelScope.cancel()``
    * ``CapacityLimiter.acquire_nowait()``
    * ``CapacityLimiter.acquire_on_behalf_of_nowait()``
    * ``Condition.release()``
    * ``Event.set()``
    * ``Lock.release()``
    * ``MemoryObjectSendStream.send_nowait()``
    * ``Semaphore.release()``
  * The following functions now return synchronous context managers instead of
    asynchronous context managers (and emit deprecation warnings if used as async
    context managers):

    * ``fail_after()``
    * ``move_on_after()``
    * ``open_cancel_scope()`` (now just ``CancelScope()``; see below)
    * ``open_signal_receiver()``

  * The following functions and methods have been renamed/moved (will now emit
    deprecation warnings when you use them by their old names):

    * ``create_blocking_portal()`` → ``anyio.from_thread.BlockingPortal()``
    * ``create_capacity_limiter()`` → ``anyio.CapacityLimiter()``
    * ``create_event()`` → ``anyio.Event()``
    * ``create_lock()`` → ``anyio.Lock()``
    * ``create_condition()`` → ``anyio.Condition()``
    * ``create_semaphore()`` → ``anyio.Semaphore()``
    * ``current_default_worker_thread_limiter()`` →
      ``anyio.to_thread.current_default_thread_limiter()``
    * ``open_cancel_scope()`` → ``anyio.CancelScope()``
    * ``run_sync_in_worker_thread()`` → ``anyio.to_thread.run_sync()``
    * ``run_async_from_thread()`` → ``anyio.from_thread.run()``
    * ``run_sync_from_thread()`` → ``anyio.from_thread.run_sync()``
    * ``BlockingPortal.spawn_task`` → ``BlockingPortal.start_task_soon``
    * ``CapacityLimiter.set_total_tokens()`` → ``limiter.total_tokens = ...``
    * ``TaskGroup.spawn()`` → ``TaskGroup.start_soon()``

  * **BACKWARDS INCOMPATIBLE** ``start_blocking_portal()`` must now be used as a context
    manager (it no longer returns a BlockingPortal, but a context manager that yields
    one)
  * **BACKWARDS INCOMPATIBLE** The ``BlockingPortal.stop_from_external_thread()`` method
    (use ``portal.call(portal.stop)`` instead now)
  * **BACKWARDS INCOMPATIBLE** The ``SocketStream`` and ``SocketListener`` classes were
    made non-generic
  * Made all non-frozen dataclasses hashable with ``eq=False``
  * Removed ``__slots__`` from ``BlockingPortal``

  See the :doc:`migration documentation <migration>` for instructions on how to deal
  with these changes.
- Improvements to running synchronous code:

  * Added the ``run_sync_from_thread()`` function
  * Added the ``run_sync_in_process()`` function for running code in worker processes
    (big thanks to Richard Sheridan for his help on this one!)
- Improvements to sockets and streaming:

  * Added the ``UNIXSocketStream`` class which is capable of sending and receiving file
    descriptors
  * Added the ``FileReadStream`` and ``FileWriteStream`` classes
  * ``create_unix_listener()`` now removes any existing socket at the given path before
    proceeding (instead of raising ``OSError: Address already in use``)
- Improvements to task groups and cancellation:

  * Added the ``TaskGroup.start()`` method and a corresponding
    ``BlockingPortal.start_task()`` method
  * Added the ``name`` argument to ``BlockingPortal.start_task_soon()``
    (renamed from ``BlockingPortal.spawn_task()``)
  * Changed ``CancelScope.deadline`` to be writable
  * Added the following functions in the ``anyio.lowlevel`` module:

    * ``checkpoint()``
    * ``checkpoint_if_cancelled()``
    * ``cancel_shielded_checkpoint()``
- Improvements and changes to synchronization primitives:

  * Added the ``Lock.acquire_nowait()``, ``Condition.acquire_nowait()`` and
    ``Semaphore.acquire_nowait()`` methods
  * Added the ``statistics()`` method to ``Event``, ``Lock``, ``Condition``, ``Semaphore``,
    ``CapacityLimiter``, ``MemoryObjectReceiveStream`` and ``MemoryObjectSendStream``
  * ``Lock`` and ``Condition`` can now only be released by the task that acquired them.
    This behavior is now consistent on all backends whereas previously only Trio
    enforced this.
  * The ``CapacityLimiter.total_tokens`` property is now writable and
    ``CapacityLimiter.set_total_tokens()`` has been deprecated
  * Added the ``max_value`` property to ``Semaphore``
- Asyncio specific improvements (big thanks to Thomas Grainger for his effort on most of
  these!):

  * Cancel scopes are now properly enforced with native asyncio coroutine functions
    (without any explicit AnyIO checkpoints)
  * Changed the asyncio ``CancelScope`` to raise a ``RuntimeError`` if a cancel scope is
    being exited before it was even entered
  * Changed the asyncio test runner to capture unhandled exceptions from asynchronous
    callbacks and unbound native tasks which are then raised after the test function (or
    async fixture setup or teardown) completes
  * Changed the asyncio ``TaskGroup.start_soon()`` (formerly ``spawn()``) method to call
    the target function immediately before starting the task, for consistency across
    backends
  * Changed the asyncio ``TaskGroup.start_soon()`` (formerly ``spawn()``) method to
    avoid the use of a coroutine wrapper on Python 3.8+ and added a hint for hiding the
    wrapper in tracebacks on earlier Pythons (supported by Pytest, Sentry etc.)
  * Changed the default thread limiter on asyncio to use a ``RunVar`` so it is  scoped
    to the current event loop, thus avoiding potential conflict among multiple running
    event loops
  * Thread pooling is now used on asyncio with ``run_sync_in_worker_thread()``
  * Fixed ``current_effective_deadline()`` raising ``KeyError`` on asyncio when no
    cancel scope is active
- Added the ``RunVar`` class for scoping variables to the running event loop

**2.2.0**

- Added the ``maybe_async()`` and ``maybe_async_cm()`` functions to facilitate forward
  compatibility with AnyIO 3
- Fixed socket stream bug on asyncio where receiving a half-close from the peer would
  shut down the entire connection
- Fixed native task names not being set on asyncio on Python 3.8+
- Fixed ``TLSStream.send_eof()`` raising ``ValueError`` instead of the expected
  ``NotImplementedError``
- Fixed ``open_signal_receiver()`` on asyncio and curio hanging if the cancel scope was
  cancelled before the function could run
- Fixed Trio test runner causing unwarranted test errors on ``BaseException``
  (PR by Matthias Urlichs)
- Fixed formatted output of ``ExceptionGroup`` containing too many newlines

**2.1.0**

- Added the ``spawn_task()`` and ``wrap_async_context_manager()`` methods to
  ``BlockingPortal``
- Added the ``handshake_timeout`` and ``error_handler`` parameters to ``TLSListener``
- Fixed ``Event`` objects on the trio backend not inheriting from ``anyio.abc.Event``
- Fixed ``run_sync_in_worker_thread()`` raising ``UnboundLocalError`` on asyncio when
  cancelled
- Fixed ``send()`` on socket streams not raising any exception on asyncio, and an
  unwrapped ``BrokenPipeError`` on trio and curio when the peer has disconnected
- Fixed ``MemoryObjectSendStream.send()`` raising ``BrokenResourceError`` when the last
  receiver is closed right after receiving the item
- Fixed ``ValueError: Invalid file descriptor: -1`` when closing a ``SocketListener`` on
  asyncio

**2.0.2**

- Fixed one more case of
  ``AttributeError: 'async_generator_asend' object has no attribute 'cr_await'`` on
  asyncio

**2.0.1**

- Fixed broken ``MultiListener.extra()`` (PR by daa)
- Fixed ``TLSStream`` returning an empty bytes object instead of raising ``EndOfStream``
  when trying to receive from the stream after a closing handshake
- Fixed ``AttributeError`` when cancelling a task group's scope inside an async test
  fixture on asyncio
- Fixed ``wait_all_tasks_blocked()`` raising ``AttributeError`` on asyncio if a native
  task is waiting on an async generator's ``asend()`` method

**2.0.0**

- General new features:

  - Added support for subprocesses
  - Added support for "blocking portals" which allow running functions in the event loop
    thread from external threads
  - Added the ``anyio.aclose_forcefully()`` function for closing asynchronous resources
    as quickly as possible

- General changes/fixes:

  - **BACKWARDS INCOMPATIBLE** Some functions have been renamed or removed (see further
    below for socket/fileio API changes):

    - ``finalize()`` → (removed; use ``contextlib.aclosing()`` instead)
    - ``receive_signals()`` → ``open_signal_receiver()``
    - ``run_in_thread()`` → ``run_sync_in_worker_thread()``
    - ``current_default_thread_limiter()`` → ``current_default_worker_thread_limiter()``
    - ``ResourceBusyError`` → ``BusyResourceError``
  - **BACKWARDS INCOMPATIBLE** Exception classes were moved to the top level package
  - Dropped support for Python 3.5
  - Bumped minimum versions of trio and curio to v0.16 and v1.4, respectively
  - Changed the ``repr()`` of ``ExceptionGroup`` to match trio's ``MultiError``

- Backend specific changes and fixes:

  - ``asyncio``: Added support for ``ProactorEventLoop``. This allows asyncio
    applications to use AnyIO on Windows even without using AnyIO as the entry point.
  - ``asyncio``: The asyncio backend now uses ``asyncio.run()`` behind the scenes which
    properly shuts down async generators and cancels any leftover native tasks
  - ``curio``: Worked around the limitation where a task can only be cancelled twice
    (any cancellations beyond that were ignored)
  - ``asyncio`` + ``curio``: a cancellation check now calls ``sleep(0)``, allowing the
    scheduler to switch to a different task
  - ``asyncio`` + ``curio``: Host name resolution now uses `IDNA 2008`_ (with UTS 46
    compatibility mapping, just like trio)
  - ``asyncio`` + ``curio``: Fixed a bug where a task group would abandon its subtasks
    if its own cancel scope was cancelled while it was waiting for subtasks to finish
  - ``asyncio`` + ``curio``: Fixed recursive tracebacks when a single exception from an
    inner task group is reraised in an outer task group

- Socket/stream changes:

  - **BACKWARDS INCOMPATIBLE** The stream class structure was completely overhauled.
    There are now separate abstract base classes for receive and send streams, byte
    streams and reliable and unreliable object streams. Stream wrappers are much better
    supported by this new ABC structure and a new "typed extra attribute" system that
    lets you query the wrapper chain for the attributes you want via ``.extra(...)``.
  - **BACKWARDS INCOMPATIBLE** Socket server functionality has been refactored into a
    network-agnostic listener system
  - **BACKWARDS INCOMPATIBLE** TLS functionality has been split off from
    ``SocketStream`` and can now work over any bidirectional bytes-based stream – you
    can now establish a TLS encrypted communications pathway over UNIX sockets or even
    memory object streams. The ``TLSRequired`` exception has also been removed as it is
    no longer necessary.
  - **BACKWARDS INCOMPATIBLE** Buffering functionality (``receive_until()`` and
    ``receive_exactly()``) was split off from ``SocketStream`` into a stream wrapper
    class (``anyio.streams.buffered.BufferedByteReceiveStream``)
  - **BACKWARDS INCOMPATIBLE** IPv6 addresses are now reported as 2-tuples. If original
    4-tuple form contains a nonzero scope ID, it is appended to the address with ``%``
    as the separator.
  - **BACKWARDS INCOMPATIBLE** Byte streams (including socket streams) now raise
    ``EndOfStream`` instead of returning an empty bytes object when the stream has been
    closed from the other end
  - **BACKWARDS INCOMPATIBLE** The socket API has changes:

    - ``create_tcp_server()`` → ``create_tcp_listener()``
    - ``create_unix_server()`` → ``create_unix_listener()``
    - ``create_udp_socket()`` had some of its parameters changed:

      - ``interface`` → ``local_address``
      - ``port`` → ``local_port``
      - ``reuse_address`` was replaced with ``reuse_port`` (and sets ``SO_REUSEPORT``
        instead of ``SO_REUSEADDR``)
    - ``connect_tcp()`` had some of its parameters changed:

      - ``address`` → ``remote_address``
      - ``port`` → ``remote_port``
      - ``bind_host`` → ``local_address``
      - ``bind_port`` → (removed)
      - ``autostart_tls`` → ``tls``
      - ``tls_hostname`` (new parameter, when you want to match the certificate against
        against something else than ``remote_address``)
    - ``connect_tcp()`` now returns a ``TLSStream`` if TLS was enabled
    - ``notify_socket_closing()`` was removed, as it is no longer used by AnyIO
    - ``SocketStream`` has changes to its methods and attributes:

        - ``address`` → ``.extra(SocketAttribute.local_address)``
        - ``alpn_protocol`` → ``.extra(TLSAttribute.alpn_protocol)``
        - ``close()`` → ``aclose()``
        - ``get_channel_binding`` → ``.extra(TLSAttribute.channel_binding_tls_unique)``
        - ``cipher`` → ``.extra(TLSAttribute.cipher)``
        - ``getpeercert`` → ``.extra(SocketAttribute.peer_certificate)`` or
          ``.extra(SocketAttribute.peer_certificate_binary)``
        - ``getsockopt()`` → ``.extra(SocketAttribute.raw_socket).getsockopt(...)``
        - ``peer_address`` → ``.extra(SocketAttribute.remote_address)``
        - ``receive_chunks()`` → (removed; use ``async for`` on the stream instead)
        - ``receive_delimited_chunks()`` → (removed)
        - ``receive_exactly()`` → ``BufferedReceiveStream.receive_exactly()``
        - ``receive_some()`` → ``receive()``
        - ``receive_until()`` → ``BufferedReceiveStream.receive_until()``
        - ``send_all()`` → ``send()``
        - ``setsockopt()`` → ``.extra(SocketAttribute.raw_socket).setsockopt(...)``
        - ``shared_ciphers`` → ``.extra(TLSAttribute.shared_ciphers)``
        - ``server_side`` → ``.extra(TLSAttribute.server_side)``
        - ``start_tls()`` → ``stream = TLSStream.wrap(...)``
        - ``tls_version`` → ``.extra(TLSAttribute.tls_version)``
    - ``UDPSocket`` has changes to its methods and attributes:

      - ``address`` → ``.extra(SocketAttribute.local_address)``
      - ``getsockopt()`` → ``.extra(SocketAttribute.raw_socket).getsockopt(...)``
      - ``port`` → ``.extra(SocketAttribute.local_port)``
      - ``receive()`` no longer takes a maximum bytes argument
      - ``receive_packets()`` → (removed; use ``async for`` on the UDP socket instead)
      - ``send()`` → requires a tuple for destination now (address, port), for
        compatibility with the new ``UnreliableObjectStream`` interface. The
        ``sendto()`` method works like the old ``send()`` method.
      - ``setsockopt()`` → ``.extra(SocketAttribute.raw_socket).setsockopt(...)``
  - **BACKWARDS INCOMPATIBLE** Renamed the ``max_size`` parameter to ``max_bytes``
    wherever it occurred (this was inconsistently named ``max_bytes`` in some subclasses
    before)
  - Added memory object streams as a replacement for queues
  - Added stream wrappers for encoding/decoding unicode strings
  - Support for the ``SO_REUSEPORT`` option (allows binding more than one socket to the
    same address/port combination, as long as they all have this option set) has been
    added to TCP listeners and UDP sockets
  - The ``send_eof()`` method was added to all (bidirectional) streams

- File I/O changes:

  - **BACKWARDS INCOMPATIBLE** Asynchronous file I/O functionality now uses a common
    code base (``anyio.AsyncFile``) instead of backend-native classes
  - **BACKWARDS INCOMPATIBLE** The File I/O API has changes to its functions and
    methods:

    - ``aopen()`` → ``open_file()``
    - ``AsyncFileclose()`` → ``AsyncFileaclose()``

- Task synchronization changes:

  - **BACKWARDS INCOMPATIBLE** Queues were replaced by memory object streams
  - **BACKWARDS INCOMPATIBLE** Added the ``acquire()`` and ``release()`` methods to the
    ``Lock``, ``Condition`` and ``Semaphore`` classes
  - **BACKWARDS INCOMPATIBLE** Removed the ``Event.clear()`` method. You must now
    replace the event object with a new one rather than clear the old one.
  - Fixed ``Condition.wait()`` not working on asyncio and curio (PR by Matt Westcott)

- Testing changes:

  - **BACKWARDS INCOMPATIBLE** Removed the ``--anyio-backends`` command line option for
    the pytest plugin. Use the ``-k`` option to do ad-hoc filtering, and the
    ``anyio_backend`` fixture to control which backends you wish to run the tests by
    default.
  - The pytest plugin was refactored to run the test and all its related async fixtures
    inside the same event loop, making async fixtures much more useful
  - Fixed Hypothesis support in the pytest plugin (it was not actually running the
    Hypothesis tests at all)

.. _IDNA 2008: https://tools.ietf.org/html/rfc5895

**1.4.0**

- Added async name resolution functions (``anyio.getaddrinfo()`` and
  ``anyio.getnameinfo()``)
- Added the ``family`` and ``reuse_address`` parameters to ``anyio.create_udp_socket()``
  (Enables multicast support; test contributed by Matthias Urlichs)
- Fixed ``fail.after(0)`` not raising a timeout error on asyncio and curio
- Fixed ``move_on_after()`` and ``fail_after()`` getting stuck on curio in some
  circumstances
- Fixed socket operations not allowing timeouts to cancel the task
- Fixed API documentation on ``Stream.receive_until()`` which claimed that the delimiter
  will be included in the returned data when it really isn't
- Harmonized the default task names across all backends
- ``wait_all_tasks_blocked()`` no longer considers tasks waiting on ``sleep(0)`` to be
  blocked on asyncio and curio
- Fixed the type of the ``address`` parameter in ``UDPSocket.send()`` to include
  ``IPAddress`` objects (which were already supported by the backing implementation)
- Fixed ``UDPSocket.send()`` to resolve host names using ``anyio.getaddrinfo()`` before
  calling ``socket.sendto()`` to avoid blocking on synchronous name resolution
- Switched to using ``anyio.getaddrinfo()`` for name lookups

**1.3.1**

- Fixed warnings caused by trio 0.15
- Worked around a compatibility issue between uvloop and Python 3.9 (missing
  ``shutdown_default_executor()`` method)

**1.3.0**

- Fixed compatibility with Curio 1.0
- Made it possible to assert fine grained control over which AnyIO backends and backend
  options are being used with each test
- Added the ``address`` and ``peer_address`` properties to the ``SocketStream``
  interface

**1.2.3**

- Repackaged release (v1.2.2 contained extra files from an experimental
  branch which broke imports)

**1.2.2**

- Fixed ``CancelledError`` leaking from a cancel scope on asyncio if the task previously
  received a cancellation exception
- Fixed ``AttributeError`` when cancelling a generator-based task (asyncio)
- Fixed ``wait_all_tasks_blocked()`` not working with generator-based tasks (asyncio)
- Fixed an unnecessary delay in ``connect_tcp()`` if an earlier attempt succeeds
- Fixed ``AssertionError`` in ``connect_tcp()`` if multiple connection attempts succeed
  simultaneously

**1.2.1**

- Fixed cancellation errors leaking from a task group when they are contained in an
  exception group
- Fixed trio v0.13 compatibility on Windows
- Fixed inconsistent queue capacity across backends when capacity was defined as 0
  (trio = 0, others = infinite)
- Fixed socket creation failure crashing ``connect_tcp()``

**1.2.0**

- Added the possibility to parametrize regular pytest test functions against the
  selected list of backends
- Added the ``set_total_tokens()`` method to ``CapacityLimiter``
- Added the ``anyio.current_default_thread_limiter()`` function
- Added the ``cancellable`` parameter to ``anyio.run_in_thread()``
- Implemented the Happy Eyeballs (:rfc:`6555`) algorithm for ``anyio.connect_tcp()``
- Fixed ``KeyError`` on asyncio and curio where entering and exiting a cancel scope
  happens in different tasks
- Fixed deprecation warnings on Python 3.8 about the ``loop`` argument of
  ``asyncio.Event()``
- Forced the use ``WindowsSelectorEventLoopPolicy`` in ``asyncio.run`` when on Windows
  and asyncio
  to keep network functionality working
- Worker threads are now spawned with ``daemon=True`` on all backends, not just trio
- Dropped support for trio v0.11

**1.1.0**

- Added the ``lock`` parameter to ``anyio.create_condition()`` (PR by Matthias Urlichs)
- Added async iteration for queues (PR by Matthias Urlichs)
- Added capacity limiters
- Added the possibility of using capacity limiters for limiting the maximum number of
  threads
- Fixed compatibility with trio v0.12
- Fixed IPv6 support in ``create_tcp_server()``, ``connect_tcp()`` and
  ``create_udp_socket()``
- Fixed mishandling of task cancellation while the task is running a worker thread on
  asyncio and curio

**1.0.0**

- Fixed pathlib2_ compatibility with ``anyio.aopen()``
- Fixed timeouts not propagating from nested scopes on asyncio and curio (PR by Matthias
  Urlichs)
- Fixed incorrect call order in socket close notifications on asyncio (mostly affecting
  Windows)
- Prefixed backend module names with an underscore to better indicate privateness

 .. _pathlib2: https://pypi.org/project/pathlib2/

**1.0.0rc2**

- Fixed some corner cases of cancellation where behavior on asyncio and curio did not
  match with that of trio. Thanks to Joshua Oreman for help with this.
- Fixed ``current_effective_deadline()`` not taking shielded cancellation scopes into
  account on asyncio and curio
- Fixed task cancellation not happening right away on asyncio and curio when a cancel
  scope is entered when the deadline has already passed
- Fixed exception group containing only cancellation exceptions not being swallowed by a
  timed out cancel scope on asyncio and curio
- Added the ``current_time()`` function
- Replaced ``CancelledError`` with ``get_cancelled_exc_class()``
- Added support for Hypothesis_
- Added support for :pep:`561`
- Use uvloop for the asyncio backend by default when available (but only on CPython)

.. _Hypothesis: https://hypothesis.works/

**1.0.0rc1**

- Fixed ``setsockopt()`` passing options to the underlying method in the wrong manner
- Fixed cancellation propagation from nested task groups
- Fixed ``get_running_tasks()`` returning tasks from other event loops
- Added the ``parent_id`` attribute to ``anyio.TaskInfo``
- Added the ``get_current_task()`` function
- Added guards to protect against concurrent read/write from/to sockets by multiple
  tasks
- Added the ``notify_socket_close()`` function

**1.0.0b2**

- Added introspection of running tasks via ``anyio.get_running_tasks()``
- Added the ``getsockopt()`` and ``setsockopt()`` methods to the ``SocketStream`` API
- Fixed mishandling of large buffers by ``BaseSocket.sendall()``
- Fixed compatibility with (and upgraded minimum required version to) trio v0.11

**1.0.0b1**

- Initial release
