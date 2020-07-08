API reference
=============

Event loop
----------

.. autofunction:: anyio.run

Miscellaneous
-------------

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

.. autofunction:: anyio.run_sync_in_worker_thread
.. autofunction:: anyio.run_async_from_thread
.. autofunction:: anyio.current_default_worker_thread_limiter

Async file I/O
--------------

.. autofunction:: anyio.open_file

.. autoclass:: anyio.fileio.AsyncFile

Streams
-------

.. autoclass:: anyio.abc.UnreliableObjectReceiveStream
.. autoclass:: anyio.abc.UnreliableObjectSendStream
.. autoclass:: anyio.abc.UnreliableObjectStream
.. autoclass:: anyio.abc.ObjectReceiveStream
.. autoclass:: anyio.abc.ObjectSendStream
.. autoclass:: anyio.abc.ObjectStream
.. autoclass:: anyio.abc.ByteReceiveStream
.. autoclass:: anyio.abc.ByteSendStream
.. autoclass:: anyio.abc.ByteStream

Sockets and networking
----------------------

.. autofunction:: anyio.connect_tcp
.. autofunction:: anyio.connect_unix
.. autofunction:: anyio.create_tcp_server
.. autofunction:: anyio.create_unix_server
.. autofunction:: anyio.create_udp_socket
.. autofunction:: anyio.getaddrinfo
.. autofunction:: anyio.getnameinfo
.. autofunction:: anyio.wait_socket_readable
.. autofunction:: anyio.wait_socket_writable
.. autofunction:: anyio.notify_socket_close

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
.. autofunction:: anyio.create_capacity_limiter

.. autoclass:: anyio.abc.Semaphore
    :members:

.. autoclass:: anyio.abc.Lock
    :members:

.. autoclass:: anyio.abc.Event
    :members:

.. autoclass:: anyio.abc.Condition
    :members:

.. autoclass:: anyio.abc.CapacityLimiter
    :members:

Operating system signals
------------------------

.. autofunction:: anyio.open_signal_receiver

Testing and debugging
---------------------

.. autoclass:: anyio.TaskInfo
.. autofunction:: anyio.get_current_task
.. autofunction:: anyio.get_running_tasks
.. autofunction:: anyio.wait_all_tasks_blocked
