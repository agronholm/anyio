Version history
===============

This library adheres to `Semantic Versioning 2.0 <http://semver.org/>`_.

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
