Version history
===============

This library adheres to `Semantic Versioning 2.0 <http://semver.org/>`_.

**2.2.0**

- Added the ``maybe_async()`` and ``maybe_async_cm()`` functions to facilitate forward
  compatibility with AnyIO 3
- Fixed socket stream bug on asyncio where receiving a half-close from the peer would shut down the
  entire connection
- Fixed native task names not being set on asyncio on Python 3.8+
- Fixed ``TLSStream.send_eof()`` raising ``ValueError`` instead of the expected
  ``NotImplementedError``
- Fixed ``open_signal_receiver()`` on asyncio and curio hanging if the cancel scope was cancelled
  before the function could run
- Fixed Trio test runner causing unwarranted test errors on ``BaseException``s
  (PR by Matthias Urlichs)
- Fixed formatted output of ``ExceptionGroup`` containing too many newlines

**2.1.0**

- Added the ``spawn_task()`` and ``wrap_async_context_manager()`` methods to ``BlockingPortal``
- Added the ``handshake_timeout`` and ``error_handler`` parameters to ``TLSListener``
- Fixed ``Event`` objects on the trio backend not inheriting from ``anyio.abc.Event``
- Fixed ``run_sync_in_worker_thread()`` raising ``UnboundLocalError`` on asyncio when cancelled
- Fixed ``send()`` on socket streams not raising any exception on asyncio, and an unwrapped
  ``BrokenPipeError`` on trio and curio when the peer has disconnected
- Fixed ``MemoryObjectSendStream.send()`` raising ``BrokenResourceError`` when the last receiver is
  closed right after receiving the item
- Fixed ``ValueError: Invalid file descriptor: -1`` when closing a ``SocketListener`` on asyncio

**2.0.2**

- Fixed one more case of
  ``AttributeError: 'async_generator_asend' object has no attribute 'cr_await'`` on asyncio

**2.0.1**

- Fixed broken ``MultiListener.extra()`` (PR by daa)
- Fixed ``TLSStream`` returning an empty bytes object instead of raising ``EndOfStream`` when
  trying to receive from the stream after a closing handshake
- Fixed ``AttributeError`` when cancelling a task group's scope inside an async test fixture on
  asyncio
- Fixed ``wait_all_tasks_blocked()`` raising ``AttributeError`` on asyncio if a native task is
  waiting on an async generator's ``asend()`` method

**2.0.0**

- General new features:

  - Added support for subprocesses
  - Added support for "blocking portals" which allow running functions in the event loop thread
    from external threads
  - Added the ``anyio.aclose_forcefully()`` function for closing asynchronous resources as quickly
    as possible

- General changes/fixes:

  - **BACKWARDS INCOMPATIBLE** Some functions have been renamed or removed (see further below for
    socket/fileio API changes):

    - ``finalize()`` → (removed; use ``async_generator.aclosing()`` instead)
    - ``receive_signals()`` → ``open_signal_receiver()``
    - ``run_in_thread()`` → ``run_sync_in_worker_thread()``
    - ``current_default_thread_limiter()`` → ``current_default_worker_thread_limiter()``
    - ``ResourceBusyError`` → ``BusyResourceError``
  - **BACKWARDS INCOMPATIBLE** Exception classes were moved to the top level package
  - Dropped support for Python 3.5
  - Bumped minimum versions of trio and curio to v0.16 and v1.4, respectively
  - Changed the ``repr()`` of ``ExceptionGroup`` to match trio's ``MultiError``

- Backend specific changes and fixes:

  - ``asyncio``: Added support for ``ProactorEventLoop``. This allows asyncio applications to use
    AnyIO on Windows even without using AnyIO as the entry point.
  - ``asyncio``: The asyncio backend now uses ``asyncio.run()`` behind the scenes which properly
    shuts down async generators and cancels any leftover native tasks
  - ``curio``: Worked around the limitation where a task can only be cancelled twice (any
    cancellations beyond that were ignored)
  - ``asyncio`` + ``curio``: a cancellation check now calls ``sleep(0)``, allowing the scheduler to
    switch to a different task
  - ``asyncio`` + ``curio``: Host name resolution now uses `IDNA 2008`_ (with UTS 46 compatibility
    mapping, just like trio)
  - ``asyncio`` + ``curio``: Fixed a bug where a task group would abandon its subtasks if its own
    cancel scope was cancelled while it was waiting for subtasks to finish
  - ``asyncio`` + ``curio``: Fixed recursive tracebacks when a single exception from an inner task
    group is reraised in an outer task group

- Socket/stream changes:

  - **BACKWARDS INCOMPATIBLE** The stream class structure was completely overhauled. There are now
    separate abstract base classes for receive and send streams, byte streams and reliable and
    unreliable object streams. Stream wrappers are much better supported by this new ABC structure
    and a new "typed extra attribute" system that lets you query the wrapper chain for the
    attributes you want via ``.extra(...)``.
  - **BACKWARDS INCOMPATIBLE** Socket server functionality has been refactored into a
    network-agnostic listener system
  - **BACKWARDS INCOMPATIBLE** TLS functionality has been split off from ``SocketStream`` and can
    now work over any bidirectional bytes-based stream – you can now establish a TLS encrypted
    communications pathway over UNIX sockets or even memory object streams. The ``TLSRequired``
    exception has also been removed as it is no longer necessary.
  - **BACKWARDS INCOMPATIBLE** Buffering functionality (``receive_until()`` and
    ``receive_exactly()``) was split off from ``SocketStream`` into a stream wrapper class
    (``anyio.streams.buffered.BufferedByteReceiveStream``)
  - **BACKWARDS INCOMPATIBLE** IPv6 addresses are now reported as 2-tuples. If original 4-tuple
    form contains a nonzero scope ID, it is appended to the address with ``%`` as the separator.
  - **BACKWARDS INCOMPATIBLE** Byte streams (including socket streams) now raise ``EndOfStream``
    instead of returning an empty bytes object when the stream has been closed from the other end
  - **BACKWARDS INCOMPATIBLE** The socket API has changes:

    - ``create_tcp_server()`` → ``create_tcp_listener()``
    - ``create_unix_server()`` → ``create_unix_listener()``
    - ``create_udp_socket()`` had some of its parameters changed:

      - ``interface`` → ``local_address``
      - ``port`` → ``local_port``
      - ``reuse_address`` was replaced with ``reuse_port`` (and sets ``SO_REUSEPORT`` instead of
        ``SO_REUSEADDR``)
    - ``connect_tcp()`` had some of its parameters changed:

      - ``address`` → ``remote_address``
      - ``port`` → ``remote_port``
      - ``bind_host`` → ``local_address``
      - ``bind_port`` → (removed)
      - ``autostart_tls`` → ``tls``
      - ``tls_hostname`` (new parameter, when you want to match the certificate against against
        something else than ``remote_address``)
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
      - ``send()`` → requires a tuple for destination now (address, port), for compatibility with
        the new ``UnreliableObjectStream`` interface. The ``sendto()`` method works like the old
        ``send()`` method.
      - ``setsockopt()`` → ``.extra(SocketAttribute.raw_socket).setsockopt(...)``
  - **BACKWARDS INCOMPATIBLE** Renamed the ``max_size`` parameter to ``max_bytes`` wherever it
    occurred (this was inconsistently named ``max_bytes`` in some subclasses before)
  - Added memory object streams as a replacement for queues
  - Added stream wrappers for encoding/decoding unicode strings
  - Support for the ``SO_REUSEPORT`` option (allows binding more than one socket to the same
    address/port combination, as long as they all have this option set) has been added to TCP
    listeners and UDP sockets
  - The ``send_eof()`` method was added to all (bidirectional) streams

- File I/O changes:

  - **BACKWARDS INCOMPATIBLE** Asynchronous file I/O functionality now uses a common code base
    (``anyio.AsyncFile``) instead of backend-native classes
  - **BACKWARDS INCOMPATIBLE** The File I/O API has changes to its functions and methods:

    - ``aopen()`` → ``open_file()``
    - ``AsyncFileclose()`` → ``AsyncFileaclose()``

- Task synchronization changes:

  - **BACKWARDS INCOMPATIBLE** Queues were replaced by memory object streams
  - **BACKWARDS INCOMPATIBLE** Added the ``acquire()`` and ``release()`` methods to the ``Lock``,
    ``Condition`` and ``Semaphore`` classes
  - **BACKWARDS INCOMPATIBLE** Removed the ``Event.clear()`` method. You must now replace the event
    object with a new one rather than clear the old one.
  - Fixed ``Condition.wait()`` not working on asyncio and curio (PR by Matt Westcott)

- Testing changes:

  - **BACKWARDS INCOMPATIBLE** Removed the ``--anyio-backends`` command line option for the pytest
    plugin. Use the ``-k`` option to do ad-hoc filtering, and the ``anyio_backend`` fixture to
    control which backends you wish to run the tests by default.
  - The pytest plugin was refactored to run the test and all its related async fixtures inside the
    same event loop, making async fixtures much more useful
  - Fixed Hypothesis support in the pytest plugin (it was not actually running the Hypothesis
    tests at all)

.. _IDNA 2008: https://tools.ietf.org/html/rfc5895

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
