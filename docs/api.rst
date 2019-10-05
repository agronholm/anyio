API reference
=============

Event loop
----------

.. autofunction:: anyio.run

Miscellaneous
-------------

.. autofunction:: anyio.finalize
.. autofunction:: anyio.sleep(delay)
.. autofunction:: anyio.get_cancelled_exc_class

Timeouts and cancellation
-------------------------

.. autofunction:: anyio.open_cancel_scope
.. autofunction:: anyio.move_on_after
.. autofunction:: anyio.fail_after
.. autofunction:: anyio.current_effective_deadline
.. autofunction:: anyio.current_time

.. autoclass:: anyio.abc.CancelScope
    :members:

Task groups
-----------

.. autofunction:: anyio.create_task_group

.. autoclass:: anyio.abc.TaskGroup
    :members:

Threads
-------

.. autofunction:: anyio.run_in_thread
.. autofunction:: anyio.run_async_from_thread
.. autofunction:: anyio.current_default_thread_limiter

Async file I/O
--------------

.. autofunction:: anyio.aopen

.. autoclass:: anyio.abc.AsyncFile

Sockets and networking
----------------------

.. autofunction:: anyio.connect_tcp
.. autofunction:: anyio.connect_unix
.. autofunction:: anyio.create_tcp_server
.. autofunction:: anyio.create_unix_server
.. autofunction:: anyio.create_udp_socket
.. autofunction:: anyio.wait_socket_readable
.. autofunction:: anyio.wait_socket_writable
.. autofunction:: anyio.notify_socket_close

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
.. autofunction:: anyio.create_capacity_limiter

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

.. autoclass:: anyio.abc.CapacityLimiter
    :members:

Operating system signals
------------------------

.. autofunction:: anyio.receive_signals

Testing and debugging
---------------------

.. autoclass:: anyio.TaskInfo
.. autofunction:: anyio.get_current_task
.. autofunction:: anyio.get_running_tasks
.. autofunction:: anyio.wait_all_tasks_blocked
