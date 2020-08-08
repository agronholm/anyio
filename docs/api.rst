API reference
=============

Event loop
----------

.. autofunction:: anyio.run
.. autofunction:: anyio.get_all_backends
.. autofunction:: anyio.get_cancelled_exc_class

Miscellaneous
-------------

.. autofunction:: anyio.sleep(delay)
.. autofunction:: anyio.aclose_forcefully

Timeouts and cancellation
-------------------------

.. autofunction:: anyio.open_cancel_scope
.. autofunction:: anyio.move_on_after
.. autofunction:: anyio.fail_after
.. autofunction:: anyio.current_effective_deadline
.. autofunction:: anyio.current_time

.. autoclass:: anyio.abc.tasks.CancelScope
    :members:

Task groups
-----------

.. autofunction:: anyio.create_task_group

.. autoclass:: anyio.abc.tasks.TaskGroup
    :members:

Threads
-------

.. autofunction:: anyio.run_sync_in_worker_thread
.. autofunction:: anyio.run_async_from_thread
.. autofunction:: anyio.current_default_worker_thread_limiter

Async file I/O
--------------

.. autofunction:: anyio.open_file

.. autoclass:: anyio.AsyncFile


Streams and stream wrappers
---------------------------

.. autoclass:: anyio.abc.streams.UnreliableObjectReceiveStream
.. autoclass:: anyio.abc.streams.UnreliableObjectSendStream
.. autoclass:: anyio.abc.streams.UnreliableObjectStream
.. autoclass:: anyio.abc.streams.ObjectReceiveStream
.. autoclass:: anyio.abc.streams.ObjectSendStream
.. autoclass:: anyio.abc.streams.ObjectStream
.. autoclass:: anyio.abc.streams.ByteReceiveStream
.. autoclass:: anyio.abc.streams.ByteSendStream
.. autoclass:: anyio.abc.streams.ByteStream
.. autoclass:: anyio.abc.streams.Listener
.. autodata:: anyio.abc.streams.AnyUnreliableByteReceiveStream
.. autodata:: anyio.abc.streams.AnyUnreliableByteSendStream
.. autodata:: anyio.abc.streams.AnyUnreliableByteStream
.. autodata:: anyio.abc.streams.AnyByteReceiveStream
.. autodata:: anyio.abc.streams.AnyByteSendStream
.. autodata:: anyio.abc.streams.AnyByteStream

.. autofunction:: anyio.create_memory_object_stream

.. autoclass:: anyio.streams.buffered.BufferedByteReceiveStream
    :members:

.. autoclass:: anyio.streams.memory.MemoryObjectReceiveStream
    :members:

.. autoclass:: anyio.streams.memory.MemoryObjectSendStream
    :members:

.. autoclass:: anyio.streams.stapled.MultiListener
    :members:

.. autoclass:: anyio.streams.stapled.StapledByteStream
    :members:

.. autoclass:: anyio.streams.stapled.StapledObjectStream
    :members:

.. autoclass:: anyio.streams.text.TextReceiveStream
    :members:

.. autoclass:: anyio.streams.text.TextSendStream
    :members:

.. autoclass:: anyio.streams.text.TextStream
    :members:

.. autoclass:: anyio.streams.tls.TLSStream
    :members:

.. autoclass:: anyio.streams.tls.TLSListener
    :members:

Sockets and networking
----------------------

.. autofunction:: anyio.connect_tcp
.. autofunction:: anyio.connect_tcp_with_tls
.. autofunction:: anyio.connect_unix
.. autofunction:: anyio.create_tcp_listener
.. autofunction:: anyio.create_unix_listener
.. autofunction:: anyio.create_udp_socket
.. autofunction:: anyio.create_connected_udp_socket
.. autofunction:: anyio.getaddrinfo
.. autofunction:: anyio.getnameinfo
.. autofunction:: anyio.wait_socket_readable
.. autofunction:: anyio.wait_socket_writable

.. autoclass:: anyio.abc.sockets.SocketStream
    :members:
    :show-inheritance:

.. autoclass:: anyio.abc.sockets.SocketListener
    :members:
    :show-inheritance:

.. autoclass:: anyio.abc.sockets.UDPSocket
    :members:

.. autoclass:: anyio.abc.sockets.ConnectedUDPSocket
    :members:

Subprocesses
------------

.. autofunction:: anyio.run_process
.. autofunction:: anyio.open_process

.. autoclass:: anyio.abc.subprocesses.Process
    :members:

Synchronization
---------------

.. autofunction:: anyio.create_semaphore
.. autofunction:: anyio.create_lock
.. autofunction:: anyio.create_event
.. autofunction:: anyio.create_condition
.. autofunction:: anyio.create_capacity_limiter

.. autoclass:: anyio.abc.synchronization.Semaphore
    :members:

.. autoclass:: anyio.abc.synchronization.Lock
    :members:

.. autoclass:: anyio.abc.synchronization.Event
    :members:

.. autoclass:: anyio.abc.synchronization.Condition
    :members:

.. autoclass:: anyio.abc.synchronization.CapacityLimiter
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

Exceptions
----------

.. autoexception:: anyio.exceptions.BrokenResourceError
.. autoexception:: anyio.exceptions.BusyResourceError
.. autoexception:: anyio.exceptions.ClosedResourceError
.. autoexception:: anyio.exceptions.DelimiterNotFound
.. autoexception:: anyio.exceptions.EndOfStream
.. autoexception:: anyio.exceptions.ExceptionGroup
    :members:

.. autoexception:: anyio.exceptions.IncompleteRead
.. autoexception:: anyio.exceptions.WouldBlock
