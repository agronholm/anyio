API reference
=============

Event loop
----------

.. autofunction:: anyio.run
.. autofunction:: anyio.get_all_backends
.. autofunction:: anyio.get_cancelled_exc_class
.. autofunction:: anyio.sleep
.. autofunction:: anyio.current_time

Asynchronous resources
----------------------

.. autofunction:: anyio.aclose_forcefully

.. autoclass:: anyio.abc.AsyncResource

Typed attributes
----------------

.. autofunction:: anyio.typed_attribute

.. autoclass:: anyio.TypedAttributeSet
.. autoclass:: anyio.TypedAttributeProvider

Timeouts and cancellation
-------------------------

.. autofunction:: anyio.open_cancel_scope
.. autofunction:: anyio.move_on_after
.. autofunction:: anyio.fail_after
.. autofunction:: anyio.current_effective_deadline

.. autoclass:: anyio.abc.CancelScope

Task groups
-----------

.. autofunction:: anyio.create_task_group

.. autoclass:: anyio.abc.TaskGroup

Threads
-------

.. autofunction:: anyio.run_sync_in_worker_thread
.. autofunction:: anyio.run_async_from_thread
.. autofunction:: anyio.current_default_worker_thread_limiter
.. autofunction:: anyio.create_blocking_portal
.. autofunction:: anyio.start_blocking_portal

.. autoclass:: anyio.abc.BlockingPortal

Async file I/O
--------------

.. autofunction:: anyio.open_file

.. autoclass:: anyio.AsyncFile


Streams and stream wrappers
---------------------------

.. autofunction:: anyio.create_memory_object_stream

.. autoclass:: anyio.abc.UnreliableObjectReceiveStream()
.. autoclass:: anyio.abc.UnreliableObjectSendStream()
.. autoclass:: anyio.abc.UnreliableObjectStream()
.. autoclass:: anyio.abc.ObjectReceiveStream()
.. autoclass:: anyio.abc.ObjectSendStream()
.. autoclass:: anyio.abc.ObjectStream()
.. autoclass:: anyio.abc.ByteReceiveStream
.. autoclass:: anyio.abc.ByteSendStream
.. autoclass:: anyio.abc.ByteStream
.. autoclass:: anyio.abc.Listener

.. autodata:: anyio.abc.AnyUnreliableByteReceiveStream
.. autodata:: anyio.abc.AnyUnreliableByteSendStream
.. autodata:: anyio.abc.AnyUnreliableByteStream
.. autodata:: anyio.abc.AnyByteReceiveStream
.. autodata:: anyio.abc.AnyByteSendStream
.. autodata:: anyio.abc.AnyByteStream

.. autoclass:: anyio.streams.buffered.BufferedByteReceiveStream
.. autoclass:: anyio.streams.memory.MemoryObjectReceiveStream
.. autoclass:: anyio.streams.memory.MemoryObjectSendStream
.. autoclass:: anyio.streams.stapled.MultiListener
.. autoclass:: anyio.streams.stapled.StapledByteStream
.. autoclass:: anyio.streams.stapled.StapledObjectStream
.. autoclass:: anyio.streams.text.TextReceiveStream
.. autoclass:: anyio.streams.text.TextSendStream
.. autoclass:: anyio.streams.text.TextStream
.. autoclass:: anyio.streams.tls.TLSAttribute
.. autoclass:: anyio.streams.tls.TLSStream
.. autoclass:: anyio.streams.tls.TLSListener

Sockets and networking
----------------------

.. autofunction:: anyio.connect_tcp
.. autofunction:: anyio.connect_unix
.. autofunction:: anyio.create_tcp_listener
.. autofunction:: anyio.create_unix_listener
.. autofunction:: anyio.create_udp_socket
.. autofunction:: anyio.create_connected_udp_socket
.. autofunction:: anyio.getaddrinfo
.. autofunction:: anyio.getnameinfo
.. autofunction:: anyio.wait_socket_readable
.. autofunction:: anyio.wait_socket_writable

.. autoclass:: anyio.abc.SocketAttribute
.. autoclass:: anyio.abc.SocketStream()
.. autoclass:: anyio.abc.SocketListener()
.. autoclass:: anyio.abc.UDPSocket()
.. autoclass:: anyio.abc.ConnectedUDPSocket()

Subprocesses
------------

.. autofunction:: anyio.run_process
.. autofunction:: anyio.open_process

.. autoclass:: anyio.abc.Process

Synchronization
---------------

.. autofunction:: anyio.create_semaphore
.. autofunction:: anyio.create_lock
.. autofunction:: anyio.create_event
.. autofunction:: anyio.create_condition
.. autofunction:: anyio.create_capacity_limiter

.. autoclass:: anyio.abc.Semaphore
.. autoclass:: anyio.abc.Lock
.. autoclass:: anyio.abc.Event
.. autoclass:: anyio.abc.Condition
.. autoclass:: anyio.abc.CapacityLimiter

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
.. autoexception:: anyio.TypedAttributeLookupError
.. autoexception:: anyio.WouldBlock
