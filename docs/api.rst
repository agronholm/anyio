API reference
=============

Event loop
----------

.. autofunction:: anyio.run
.. autofunction:: anyio.get_all_backends
.. autofunction:: anyio.get_cancelled_exc_class
.. autofunction:: anyio.sleep(delay)
.. autofunction:: anyio.current_time

Asynchronous resources
----------------------

.. autofunction:: anyio.aclose_forcefully

.. autoclass:: anyio.abc.resources.AsyncResource

Timeouts and cancellation
-------------------------

.. autofunction:: anyio.open_cancel_scope
.. autofunction:: anyio.move_on_after
.. autofunction:: anyio.fail_after
.. autofunction:: anyio.current_effective_deadline

.. autoclass:: anyio.abc.tasks.CancelScope

Task groups
-----------

.. autofunction:: anyio.create_task_group

.. autoclass:: anyio.abc.tasks.TaskGroup

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

.. autofunction:: anyio.create_memory_object_stream

.. autoclass:: anyio.abc.streams.UnreliableObjectReceiveStream()
.. autoclass:: anyio.abc.streams.UnreliableObjectSendStream()
.. autoclass:: anyio.abc.streams.UnreliableObjectStream()
.. autoclass:: anyio.abc.streams.ObjectReceiveStream()
.. autoclass:: anyio.abc.streams.ObjectSendStream()
.. autoclass:: anyio.abc.streams.ObjectStream()
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

.. autoclass:: anyio.streams.buffered.BufferedByteReceiveStream
.. autoclass:: anyio.streams.memory.MemoryObjectReceiveStream
.. autoclass:: anyio.streams.memory.MemoryObjectSendStream
.. autoclass:: anyio.streams.stapled.MultiListener
.. autoclass:: anyio.streams.stapled.StapledByteStream
.. autoclass:: anyio.streams.stapled.StapledObjectStream
.. autoclass:: anyio.streams.text.TextReceiveStream
.. autoclass:: anyio.streams.text.TextSendStream
.. autoclass:: anyio.streams.text.TextStream
.. autoclass:: anyio.streams.tls.TLSStream
.. autoclass:: anyio.streams.tls.TLSListener

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

.. autoclass:: anyio.abc.sockets.SocketProvider()
.. autoclass:: anyio.abc.sockets.SocketStream()
.. autoclass:: anyio.abc.sockets.SocketListener()
.. autoclass:: anyio.abc.sockets.UDPSocket()
.. autoclass:: anyio.abc.sockets.ConnectedUDPSocket()

Subprocesses
------------

.. autofunction:: anyio.run_process
.. autofunction:: anyio.open_process

.. autoclass:: anyio.abc.subprocesses.Process

Synchronization
---------------

.. autofunction:: anyio.create_semaphore
.. autofunction:: anyio.create_lock
.. autofunction:: anyio.create_event
.. autofunction:: anyio.create_condition
.. autofunction:: anyio.create_capacity_limiter

.. autoclass:: anyio.abc.synchronization.Semaphore
.. autoclass:: anyio.abc.synchronization.Lock
.. autoclass:: anyio.abc.synchronization.Event
.. autoclass:: anyio.abc.synchronization.Condition
.. autoclass:: anyio.abc.synchronization.CapacityLimiter

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

.. autoexception:: anyio.BrokenResourceError
.. autoexception:: anyio.BusyResourceError
.. autoexception:: anyio.ClosedResourceError
.. autoexception:: anyio.DelimiterNotFound
.. autoexception:: anyio.EndOfStream
.. autoexception:: anyio.ExceptionGroup
.. autoexception:: anyio.IncompleteRead
.. autoexception:: anyio.WouldBlock
