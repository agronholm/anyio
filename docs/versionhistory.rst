Version history
===============

This library adheres to `Semantic Versioning <http://semver.org/>`_.

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
