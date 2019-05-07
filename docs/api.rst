API reference
=============

Event loop
----------

.. autofunction:: anyio.run

Miscellaneous
-------------

.. autofunction:: anyio.finalize
.. autocofunction:: anyio.sleep
.. autofunction:: anyio.get_cancelled_exc_class

Timeouts and cancellation
-------------------------

.. autofunction:: anyio.open_cancel_scope
.. autofunction:: anyio.move_on_after
.. autofunction:: anyio.fail_after
.. autocofunction:: anyio.current_effective_deadline
.. autocofunction:: anyio.current_time

.. autoclass:: anyio.abc.CancelScope
    :members:

Task groups
-----------

.. autofunction:: anyio.create_task_group

.. autoclass:: anyio.abc.TaskGroup
    :members:

Threads
-------

.. autocofunction:: anyio.run_in_thread
.. autofunction:: anyio.run_async_from_thread

Async file I/O
--------------

.. autocofunction:: anyio.aopen

.. autoclass:: anyio.abc.AsyncFile

Sockets and networking
----------------------

.. autocofunction:: anyio.connect_tcp
.. autocofunction:: anyio.connect_unix
.. autocofunction:: anyio.create_tcp_server
.. autocofunction:: anyio.create_unix_server
.. autocofunction:: anyio.create_udp_socket
.. autocofunction:: anyio.wait_socket_readable
.. autocofunction:: anyio.wait_socket_writable
.. autocofunction:: anyio.notify_socket_close

.. autoclass:: anyio.abc.Stream
    :members:

.. autoclass:: anyio.abc.SocketStream
    :members:
    :show-inheritance:

.. autoclass:: anyio.abc.SocketStreamServer
    :members:

.. autoclass:: anyio.abc.UDPSocket
    :members:

Synchronization
---------------

.. autofunction:: anyio.create_semaphore
.. autofunction:: anyio.create_lock
.. autofunction:: anyio.create_event
.. autofunction:: anyio.create_condition
.. autofunction:: anyio.create_queue

.. autoclass:: anyio.abc.Semaphore
    :members:

.. autoclass:: anyio.abc.Lock
    :members:

.. autoclass:: anyio.abc.Event
    :members:

.. autoclass:: anyio.abc.Condition
    :members:

.. autoclass:: anyio.abc.Queue
    :members:

Operating system signals
------------------------

.. autocofunction:: anyio.receive_signals

Testing and debugging
---------------------

.. autoclass:: anyio.TaskInfo
.. autocofunction:: anyio.get_current_task
.. autocofunction:: anyio.get_running_tasks
.. autocofunction:: anyio.wait_all_tasks_blocked
