Version history
===============

This library adheres to `Semantic Versioning 2.0 <http://semver.org/>`_.

**2.0.0rc1**

- **BACKWARDS INCOMPATIBLE** Replaced individual stream/listener attributes with a system of
  typed extra attributes which traverses the entire chain of wrapped streams/listeners to find the
  attribute being looked for
- **BACKWARDS INCOMPATIBLE** Merged ``connect_tcp_with_tls()`` back into ``connect_tcp()``
- Added the ``tls_standard_compatible`` argument to ``connect_tcp()`` (this was mistakenly omitted
  when ``connect_tcp()`` was split in two)
- Fixed Hypothesis support in the pytest plugin (it was not actually running the Hypothesis tests
  at all)

**2.0.0b2**

- Simplified the cancellation logic in curio's cancel scopes (fixes runaway ``curio.TaskTimeout``
  exceptions)
- Fixed return type annotation for ``BlockingPortal.call()`` to return the coroutine function's
  return value and not the coroutine object
- Changed the logic in ``MemoryObjectReceiveStream.receive()`` to ignore the cancellation exception
  instead of passing the item to the next receiver or the buffer

**2.0.0b1**

- New features:

  - Added support for subprocesses
  - Added support for "blocking portals" which allow running functions in the event loop thread
    from external threads
  - Added the ``anyio.aclose_forcefully()`` function for closing asynchronous resources as quickly
    as possible
  - Added support for ``ProactorEventLoop`` on the asyncio backend. This allows asyncio
    applications to use AnyIO on Windows even without using AnyIO as the entry point.
  - Added memory object streams as a replacement for queues
  - The pytest plugin was refactored to run the test and all its related async fixtures inside the
    same event loop, making async fixtures much more useful

- General changes/fixes:

  - Dropped support for Python 3.5
  - Bumped minimum versions of trio and curio to v0.16 and v1.4, respectively
  - Unified checkpoint behavior: a cancellation check now calls ``sleep(0)`` on asyncio and
    curio, allowing the scheduler to switch to a different task
  - Fixed a bug where a task group would abandon its subtasks if its own cancel scope was
    cancelled while it was waiting for subtasks to finish
  - Fixed recursive tracebacks when a single exception from an inner task group is reraised in an
    outer task group
  - The asyncio backend now uses ``asyncio.run()`` behind the scenes which properly shuts down
    async generators and cancels any leftover native tasks
  - Worked around curio's limitation where a task can only be cancelled twice (any cancellations
    beyond that were ignored)
  - **BACKWARDS INCOMPATIBLE** Removed the ``anyio.finalize()`` context manager since as of curio
    1.0, it is no longer necessary. Use ``async_generator.aclosing()`` instead.
  - **BACKWARDS INCOMPATIBLE** Renamed some functions and methods to match their corresponding
    names in Trio:

    - ``Stream.close()`` -> ``Stream.aclose()``
    - ``AsyncFile.close()`` -> ``AsyncFile.aclose()``
    - ``anyio.aopen()`` -> ``anyio.open_file()``
    - ``anyio.receive_signals()`` -> ``anyio.open_signal_receiver()``
    - ``anyio.run_in_thread()`` -> ``anyio.run_sync_in_worker_thread()``
    - ``anyio.current_default_thread_limiter()`` -> ``anyio.current_default_worker_thread_limiter()``
    - ``anyio.exceptions.ResourceBusyError`` -> ``anyio.BusyResourceError``
  - **BACKWARDS INCOMPATIBLE** Exception classes were moved to the top level package

- Socket/stream changes:

  - **BACKWARDS INCOMPATIBLE** Renamed the ``max_size`` parameter to ``max_bytes`` wherever it
    occurred (this was inconsistently named ``max_bytes`` in some subclasses before)
  - **BACKWARDS INCOMPATIBLE** TLS functionality has been split off from ``SocketStream`` and can
    now work over arbitrary streams – you can now establish a TLS encrypted communications pathway
    using any bytes-based receive/send stream pair.
  - ``connect_tcp()`` has been split into ``connect_tcp()`` and ``connect_tcp_with_tls()``
  - **BACKWARDS INCOMPATIBLE** Socket server functionality has been refactored into a
    network-agnostic listener system
  - **BACKWARDS INCOMPATIBLE** The ``reuse_address`` option was replaced with ``reuse_port`` in
    ``create_udp_socket()``. This switches on the ``SO_REUSEPORT`` option. The ``SO_REUSEADDR`` is
    no longer used under any circumstances with UDP sockets.
  - Added the ``family`` attribute to socket streams and listeners (for getting the address family)
  - **BACKWARDS INCOMPATIBLE** Removed the ``notify_socket_closing()`` function as it is no longer
    used by AnyIO
  - Support for the ``SO_REUSEPORT`` option (allows binding more than one socket to the same
    address/port combination, as long as they all have this option set) has been added to TCP
    listeners and UDP sockets
  - The ``send_eof()`` method was added to all (bidirectional) streams
  - Added the ``raw_socket`` property on socket streams, UDP sockets and socket listeners

- File I/O changes:

  - **BACKWARDS INCOMPATIBLE** Asynchronous file I/O functionality now uses a common code base
    (``anyio.fileio.AsyncFile``) instead of backend-native classes

- Task synchronization changes:

  - **BACKWARDS INCOMPATIBLE** Added the ``acquire()`` and ``release()`` methods to the ``Lock``,
    ``Condition`` and ``Semaphore`` classes
  - **BACKWARDS INCOMPATIBLE** Removed the ``Event.clear()`` method. You must now replace the event
    object with a new one rather than clear the old one.
  - **BACKWARDS INCOMPATIBLE** Removed the ``anyio.create_queue()`` function and the ``Queue``
    class. Use memory object streams instead.
  - Fixed ``Condition.wait()`` not working on asyncio and curio (PR by Matt Westcott)

- Testing changes:

  - **BACKWARDS INCOMPATIBLE** Removed the ``--anyio-backends`` command line option for the pytest
    plugin. Use the ``-k`` option to do ad-hoc filtering, and the ``anyio_backend`` fixture to
    control which backends you wish to run the tests by default.

**1.4.0**

- Added async name resolution functions (``anyio.getaddrinfo()`` and ``anyio.getnameinfo()``)
- Added the ``family`` and ``reuse_address`` parameters to ``anyio.create_udp_socket()``
  (Enables multicast support; test contributed by Matthias Urlichs)
- Fixed ``fail.after(0)`` not raising a timeout error on asyncio and curio
- Fixed ``move_on_after()`` and ``fail_after()`` getting stuck on curio in some circumstances
- Fixed socket operations not allowing timeouts to cancel the task
- Fixed API documentation on ``Stream.receive_until()`` which claimed that the delimiter will be
  included in the returned data when it really isn't
- Harmonized the default task names across all backends
- ``wait_all_tasks_blocked()`` no longer considers tasks waiting on ``sleep(0)`` to be blocked
  on asyncio and curio
- Fixed the type of the ``address`` parameter in ``UDPSocket.send()`` to include ``IPAddress``
  objects (which were already supported by the backing implementation)
- Fixed ``UDPSocket.send()`` to resolve host names using ``anyio.getaddrinfo()`` before calling
  ``socket.sendto()`` to avoid blocking on synchronous name resolution
- Switched to using ``anyio.getaddrinfo()`` for name lookups

**1.3.1**

- Fixed warnings caused by trio 0.15
- Worked around a compatibility issue between uvloop and Python 3.9 (missing
  ``shutdown_default_executor()`` method)

**1.3.0**

- Fixed compatibility with Curio 1.0
- Made it possible to assert fine grained control over which AnyIO backends and backend options are
  being used with each test
- Added the ``address`` and ``peer_address`` properties to the ``SocketStream`` interface

**1.2.3**

- Repackaged release (v1.2.2 contained extra files from an experimental
  branch which broke imports)

**1.2.2**

- Fixed ``CancelledError`` leaking from a cancel scope on asyncio if the task previously received a
  cancellation exception
- Fixed ``AttributeError`` when cancelling a generator-based task (asyncio)
- Fixed ``wait_all_tasks_blocked()`` not working with generator-based tasks (asyncio)
- Fixed an unnecessary delay in ``connect_tcp()`` if an earlier attempt succeeds
- Fixed ``AssertionError`` in ``connect_tcp()`` if multiple connection attempts succeed
  simultaneously

**1.2.1**

- Fixed cancellation errors leaking from a task group when they are contained in an exception group
- Fixed trio v0.13 compatibility on Windows
- Fixed inconsistent queue capacity across backends when capacity was defined as 0
  (trio = 0, others = infinite)
- Fixed socket creation failure crashing ``connect_tcp()``

**1.2.0**

- Added the possibility to parametrize regular pytest test functions against the selected list of
  backends
- Added the ``set_total_tokens()`` method to ``CapacityLimiter``
- Added the ``anyio.current_default_thread_limiter()`` function
- Added the ``cancellable`` parameter to ``anyio.run_in_thread()``
- Implemented the Happy Eyeballs (:rfc:`6555`) algorithm for ``anyio.connect_tcp()``
- Fixed ``KeyError`` on asyncio and curio where entering and exiting a cancel scope happens in
  different tasks
- Fixed deprecation warnings on Python 3.8 about the ``loop`` argument of ``asyncio.Event()``
- Forced the use ``WindowsSelectorEventLoopPolicy`` in ``asyncio.run`` when on Windows and asyncio
  to keep network functionality working
- Worker threads are now spawned with ``daemon=True`` on all backends, not just trio
- Dropped support for trio v0.11

**1.1.0**

- Added the ``lock`` parameter to ``anyio.create_condition()`` (PR by Matthias Urlichs)
- Added async iteration for queues (PR by Matthias Urlichs)
- Added capacity limiters
- Added the possibility of using capacity limiters for limiting the maximum number of threads
- Fixed compatibility with trio v0.12
- Fixed IPv6 support in ``create_tcp_server()``, ``connect_tcp()`` and ``create_udp_socket()``
- Fixed mishandling of task cancellation while the task is running a worker thread on asyncio and
  curio

**1.0.0**

- Fixed pathlib2_ compatibility with ``anyio.aopen()``
- Fixed timeouts not propagating from nested scopes on asyncio and curio (PR by Matthias Urlichs)
- Fixed incorrect call order in socket close notifications on asyncio (mostly affecting Windows)
- Prefixed backend module names with an underscore to better indicate privateness

 .. _pathlib2: https://pypi.org/project/pathlib2/

**1.0.0rc2**

- Fixed some corner cases of cancellation where behavior on asyncio and curio did not match with
  that of trio. Thanks to Joshua Oreman for help with this.
- Fixed ``current_effective_deadline()`` not taking shielded cancellation scopes into account on
  asyncio and curio
- Fixed task cancellation not happening right away on asyncio and curio when a cancel scope is
  entered when the deadline has already passed
- Fixed exception group containing only cancellation exceptions not being swallowed by a timed out
  cancel scope on asyncio and curio
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
- Added guards to protect against concurrent read/write from/to sockets by multiple tasks
- Added the ``notify_socket_close()`` function

**1.0.0b2**

- Added introspection of running tasks via ``anyio.get_running_tasks()``
- Added the ``getsockopt()`` and ``setsockopt()`` methods to the ``SocketStream`` API
- Fixed mishandling of large buffers by ``BaseSocket.sendall()``
- Fixed compatibility with (and upgraded minimum required version to) trio v0.11

**1.0.0b1**

- Initial release
