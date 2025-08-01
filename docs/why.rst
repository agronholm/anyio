Why you should be using AnyIO APIs instead of asyncio APIs
==========================================================

.. py:currentmodule:: anyio

AnyIO is not just a compatibility layer for bridging asyncio and Trio_. For one, it comes with its own diverse set of
Trio-inspired APIs which have been designed to be a step up from asyncio. Secondly, asyncio has numerous design issues
and missing features that AnyIO fixes for you. Therefore there are strong merits in switching to AnyIO APIs even if
you are developing an application and not a library.

Design problems with task management
++++++++++++++++++++++++++++++++++++

While the :class:`asyncio.TaskGroup` class, introduced in Python 3.11, is a major step towards structured concurrency,
it only provides a very narrow API that severely limits its usefulness.

First and foremost, the :class:`asyncio.TaskGroup` class does not offer any way to cancel, or even list all of the
contained tasks, so in order to do that, you would still have to keep track of any tasks you create. This also makes it
problematic to pass the task group to a child tasks, as tracking the tasks becomes a lot more tedious in such cases.

Secondly, while AnyIO (and Trio_) has long provided a way to wait until a newly launched task signals readiness,
:class:`asyncio.TaskGroup` still does not provide any such mechanism, leaving users to devise their own, often
error-prone methods to achieve this.

How does AnyIO fix these problems?
----------------------------------

An AnyIO task group contains its own cancel scope which can be used to cancel all the child tasks, regardless of where
they were launched from. Furthermore, if the task group's cancel scope is cancelled, any tasks launched from the task
group since then are *also* automatically subject to cancellation, thus ensuring that nothing can accidentally hang the
task group and prevent it from exiting.

As for tasks signalling readiness, :ref:`here <start_initialize>` is an example of waiting until a child task is
ready.

.. note:: In all fairness, AnyIO's task groups have their own ergonomics issues, like the inability to retrieve the
    tasks' return values and not being easily able to cancel individual tasks. This is something that
    `#890 <https://github.com/agronholm/anyio/pull/890>`_ aims to rectify.

Design problems with cancellation
+++++++++++++++++++++++++++++++++

The most significant problems with asyncio relate to its handling of cancellation. Asyncio employs a cancellation
mechanism where cancelling a task schedules a :exc:`~asyncio.CancelledError` exception to be raised in the task (once).
This mechanism is called *edge cancellation*.

The most common problem with edge cancellation is that if the task catches the :exc:`~asyncio.CancelledError` (which
often happens by accident when the user code has a ``except BaseException:`` block and doesn't re-raise the exception),
then no further action is taken, and the task keeps happily running until it is explicitly cancelled again::

    import asyncio


    async def sleeper():
        try:
            await asyncio.sleep(1)
        except BaseException:
            pass  # the first cancellation is caught here

        # This call will never return unless the task is cancelled again
        await asyncio.sleep(float("inf"))

    async def main():
        async with asyncio.TaskGroup() as tg:
            task = tg.create_task(sleeper())
            await asyncio.sleep(0)  # ensure that the task reaches the first sleep()
            task.cancel()

        print("done")

    # Execution hangs
    asyncio.run(main())

Another issue is that if a task that has already been scheduled to resume with a value (that is, the ``await`` is about
to yield a result) is cancelled, a :exc:`~asyncio.CancelledError` will instead be raised in the task's coroutine when it
resumes, thus potentially causing the awaitable result to be lost, even if the task catches the exception::

    import asyncio


    async def receive(f):
        print(await f)
        await asyncio.sleep(1)
        print("The task will be cancelled before this is printed")


    async def main():
        f = asyncio.get_running_loop().create_future()
        task = asyncio.create_task(receive(f))
        await asyncio.sleep(0)  # make sure the task has started
        f.set_result("hello")
        task.cancel()

        # The "hello" result is lost due to the cancellation
        try:
            await task
        except asyncio.CancelledError:
            pass


    # No output
    asyncio.run(main())

Similarly, if a newly created task is cancelled, its coroutine function may never get to run and thus react to the
cancellation. While the :external+python:doc:`asyncio documentation <library/asyncio-task>` claims that:

   Tasks can easily and safely be cancelled. When a task is cancelled, :exc:`~asyncio.CancelledError` will be raised in
   the task at the next opportunity.

This is simply **not true** for tasks that are cancelled before they have had a chance to start! This is problematic in
cases where the newly launched task is responsible for managing a resource. If the task is cancelled without getting to
handle the :exc:`~asyncio.CancelledError`, it won't have a chance to close the managed resource::

    import asyncio


    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            # Here would be the code that cleanly closes the resource
            print("closed")


    async def handle_resource(resource):
        async with resource:
            ...


    async def main():
        async with asyncio.TaskGroup() as tg:
            task = tg.create_task(handle_resource(Resource()))
            task.cancel()


    # No output
    asyncio.run(main())

.. note:: :func:`Eager task factories <asyncio.eager_task_factory>` and, likewise, tasks started with
   ``eager_start=True`` do not suffer from this particular issue, as there is no opportunity to cancel the task before
   its first iteration.

Asyncio cancellation shielding is a major footgun
-------------------------------------------------

Asyncio has a function, :func:`asyncio.shield`, to shield a coroutine from cancellation. It launches a new task in such
a way that the cancellation of the task awaiting on it will not propagate to the new task.

The trouble with this is that if the host task (the task that awaits for the shielded operation to complete) **is**
cancelled, the shielded task is orphaned. If the shielded task then raises an exception, only a warning might be printed
on the console, but the exception will not propagate anywhere. Worse yet, since asyncio only holds weak references to
each task, there is nothing preventing the shielded task from being garbage collected, mid-execution::

    import asyncio
    import gc


    async def shielded_task():
        fut = asyncio.get_running_loop().create_future()
        await fut


    async def host_task():
        await asyncio.shield(shielded_task())


    async def main():
        async with asyncio.TaskGroup() as tg:
            task = tg.create_task(host_task())
            await asyncio.sleep(0)  # allow the host task to start
            task.cancel()
            await asyncio.sleep(0)  # allow the cancellation to take effect on the host task
            gc.collect()

    # Prints warning: Task was destroyed but it is pending!
    asyncio.run(main())

To make matters even worse, the shielding only prevents indirect cancellation through the host task. If the event loop
is shut down, it will automatically cancel all tasks, including the supposedly shielded one::

    import asyncio
    import signal


    async def finalizer():
        await asyncio.sleep(1)
        print("Finalizer done")

    async def main():
        ...  # the business logic goes here
        asyncio.get_running_loop().call_soon(signal.raise_signal, signal.SIGINT)  # simulate ctrl+C
        await asyncio.shield(finalizer())

    # Prints a traceback containing a KeyboardInterrupt and a CancelledError, but not the "Finalizer done" message
    asyncio.run(main())

A good practical example of the issues with :func:`~asyncio.shield` can be drawn from the `Python Redis client`_ where
the incorrect use of this function was responsible for a `significant outage of ChatGPT`_. The point here is not to lay
blame on the downstream developers, but to demonstrate that :func:`~asyncio.shield` is difficult, if not impossible, to
use correctly for any practical purpose.

.. _Python Redis client: https://github.com/redis/redis-py
.. _significant outage of ChatGPT: https://openai.com/index/march-20-chatgpt-outage/

How does AnyIO fix these problems?
----------------------------------

To provide for more precise and predictable cancellation control, AnyIO (and Trio_) uses *cancel scopes*. Cancel scopes
select sections of a coroutine function to be cancelled. Cancel scopes are stateful in nature, meaning once a cancel
scope has been cancelled, it will stay that way. On asyncio, AnyIO cancel scopes work by cancelling the enclosed task(s)
every time they try to await on something as long as the task's active cancel scope is *effectively cancelled* (i.e.
either directly or via an ancestor scope). This mechanism of stateful cancellation is called *level cancellation*.

AnyIO's cancel scopes have two notable differences from asyncio's cancellation:

#. Cancel scopes never try to cancel a task when it's scheduled to resume with a value
#. Cancel scopes always allow the task a chance to react to the cancellation

In addition to providing the ability to cancel specific code sections, cancel scopes also provide two important
features: shielding and timeouts.

Shielding a section of code from cancellation also works in a more straightforward fashion – not by launching another
task, but by preventing the propagation of cancellation from parent cancel scope to a shielded scope.

Cancel scopes with a set *deadline* are roughly equivalent to :func:`asyncio.timeout`, except for the level cancellation
semantics and the ability to combine timeouts with shielding to easily implement finalization with a timeout. The
:func:`move_on_after` context manager is often used for this purpose.

.. note:: Shielded cancel scopes only protect against cancellation by other cancel scopes, not direct calls to
    :meth:`~asyncio.Task.cancel`.

The first asyncio example above demonstrated how a task cancellation is only delivered once, unless explicitly repeated.
But with AnyIO's cancel scopes, every attempt to yield control to the event loop from a cancelled task results in a new
:exc:`~asyncio.CancelledError`::

    import asyncio

    import anyio


    async def sleeper():
        try:
            await asyncio.sleep(1)
        except BaseException:
            pass  # the first cancellation is caught here

        # This will raise another CancelledError
        await asyncio.sleep(float("inf"))

    async def main():
        async with anyio.create_task_group() as tg:
            tg.start_soon(sleeper)
            await asyncio.sleep(0)  # ensure that the task reaches the first sleep()
            tg.cancel_scope.cancel()

        print("done")

    # Output: "done"
    asyncio.run(main())

The AnyIO version of the second example demonstrates that a task which is scheduled to resume will be able to process
the result of the ``await`` before it gets cancelled::

    import asyncio

    import anyio


    async def receive(f):
        print(await f)
        await asyncio.sleep(1)
        print("The task will be cancelled before this is printed")


    async def main():
        f = asyncio.get_running_loop().create_future()
        async with anyio.create_task_group() as tg:
            tg.start_soon(receive, f)
            await asyncio.sleep(0)  # make sure the task has started
            f.set_result("hello")
            tg.cancel_scope.cancel()


    # Output: "hello"
    asyncio.run(main())

The third example demonstrated that if a newly created task is cancelled, it would not get an opportunity to react to
the cancellation. With AnyIO's task groups, they do::

    import asyncio

    import anyio


    class Resource:
        async def __aenter__(self):
            return self

        async def __aexit__(self, exc_type, exc_val, exc_tb):
            # Here would be the code that cleanly closes the resource
            print("closed")


    async def handle_resource(resource):
        async with resource:
            ...


    async def main():
        async with anyio.create_task_group() as tg:
            tg.start_soon(handle_resource, Resource())
            tg.cancel_scope.cancel()


    # Output: "closed"
    asyncio.run(main())


.. seealso:: :doc:`cancellation`

Design problems with asyncio queues
+++++++++++++++++++++++++++++++++++

While the :class:`asyncio.Queue` class was upgraded in Python 3.13 to support the notion of shutting down, there are
still a number of issues with it:

#. Queues are unbounded by default
#. Queues don't support async iteration
#. Queue shutdown doesn't play nice with multiple producers

The problem with unbounded queues is that careless use of such queues may cause runaway memory use and thus lead to out
of memory errors. This default behavior is unfortunately unfixable due to backwards compatibility reasons.

The second problem is mostly an ergonomics issue. A PR was made to address this, but was
`declined <https://github.com/python/cpython/pull/120925#issuecomment-2370151879>`_.

The third problem manifests itself when multiple producer tasks put items to the same queue. If one producer shuts down
the queue, the others will get unwarranted errors when trying to put more items to the queue. Therefore the producers
either need another means to coordinate the queue shutdown, or they need to be launched in a task group in such a manner
that the host task shuts down the queue after the producer tasks have exited. Either way, the design is not ideal for
multiple producer tasks.

.. _queue_fix:

How does AnyIO fix these problems?
----------------------------------

AnyIO offers an alternative to queues: :ref:`memory object streams <memory object streams>`. They were modeled after
Trio's `memory channels`_. When you create a memory object stream, you get a "send" stream and a "receive" stream. The
separation is necessary for the purpose of cloning (explained below). By default, memory object streams have an item
capacity of 0, meaning the stream does not store anything. In other words, a send operation will not complete until
another task shows up to receive the item.

Memory object streams support cloning. This enables each consumer and producer task to close its own clone of the
receive or send stream. Only after all clones have been closed is the respective send or receive memory object stream
considered to be closed.

Unlike :class:`asyncio.Queue`, memory object receive streams support async iteration. The ``async for`` loop then ends
naturally when all send stream clones have been closed. For send streams, attempting to send an item when all receive
stream clones have been closed raises a :exc:`BrokenResourceError`.

Memory object streams also provide better debugging facilities via the
:meth:`~.streams.memory.MemoryObjectReceiveStream.statistics` method which can tell you:

* the number of queued items
* the number of open send and receive streams
* how many tasks are waiting to send or receive to/from the stream

.. _memory channels: https://trio.readthedocs.io/en/stable/reference-core.html#using-channels-to-pass-values-between-tasks

Design problems with the streams API
++++++++++++++++++++++++++++++++++++

While asyncio provides a limited set of `stream classes`_, their callback-based design unfortunately shines through from
the API. First of all, unlike regular sockets, you get a separate reader and writer object instead of a full-duplex
stream which you would essentially get from the :mod:`socket` functions. Second, in order to send data to the stream,
you have to first call the synchronous :meth:`~asyncio.StreamWriter.write` method which adds data to the internal
buffer, and then you have to remember to call the coroutine method :meth:`~asyncio.StreamWriter.drain` which then
*actually* causes the data to be written to the underlying socket. Likewise, when you close a stream, you first have to
call :meth:`~asyncio.StreamWriter.close` and *then* await on :meth:`~asyncio.StreamWriter.wait_closed` to make sure the
stream has *actually* closed! To add insult to injury, these classes don't even support the async context manager
protocol so you can't just do ``async with writer: ...``.

Another issue lies with the :meth:`~asyncio.StreamWriter.get_extra_info` method asyncio provides to get information like
the remote address for socket connections, or the raw socket object:

#. This method only exists in the writer class, not the reader (for whatever reason).
#. It returns a dictionary, so to get the information you want, you'll need to access one of the keys in the returned
   dict, based on the documentation.
#. It is not type safe, as Typeshed specifies the return type as ``dict[str, Any]``. Therefore, static type checkers
   cannot check the correctness of any access to the returned dict based on either the keys or the value types.

.. _stream classes: https://docs.python.org/3/library/asyncio-stream.html

How does AnyIO fix these problems?
----------------------------------

AnyIO comes with hierarchy of base stream classes:

* :class:`~.abc.UnreliableObjectStream`, :class:`~.abc.UnreliableObjectReceiveStream` and
  :class:`~.abc.UnreliableObjectSendStream`: for transporting objects; no guarantees of reliable or ordered delivery,
  just like with UDP sockets
* :class:`~.abc.ObjectStream`, :class:`~.abc.ObjectReceiveStream`, :class:`~.abc.ObjectSendStream`: like the above, but
  with added guarantees about reliable and ordered delivery
* :class:`~.abc.ByteStream`, :class:`~.abc.ByteReceiveStream`, :class:`~.abc.ByteSendStream`: for transporting bytes;
  may split chunks arbitrarily, just like TCP sockets
* :class:`~.abc.SocketStream`: byte streams backed by actual sockets

These interfaces are then implemented by a number of concrete classes, such as:

* :class:`~.streams.memory.MemoryObjectReceiveStream` and :class:`~.streams.memory.MemoryObjectSendStream`: for
  exchanging arbitrary objects between tasks within the same process (see :ref:`this section <queue_fix>` for the
  rationale for the sender/receiver split)
* :class:`~.streams.buffered.BufferedByteReceiveStream` and :class:`~.streams.buffered.BufferedByteStream`: for adapting
  bytes-oriented object streams into byte streams, and for supporting read operations that require a buffer, such as
  needing to read a precise amount of bytes, or reading up to a specific delimiter
* :class:`~.streams.tls.TLSStream`: for using TLS encryption over any arbitrary (bytes-oriented) stream
* :class:`~.streams.text.TextReceiveStream` and :class:`~.streams.text.TextStream`: for turning a bytes-oriented stream
  into a unicode string-oriented stream
* :class:`~.streams.file.FileReadStream` and :class:`~.streams.file.FileWriteStream`: for reading from or writing to
  files
* :class:`~.streams.stapled.StapledObjectStream` and :class:`~.streams.stapled.StapledByteStream`: for combining
  different read and write streams into full-duplex streams

.. important:: In contrast with regular sockets or asyncio streams, AnyIO streams raise :exc:`EndOfStream` instead of
    returning an empty bytes object or ``None`` when there is no more data to be read.

.. seealso:: :doc:`streams`

As a counterpart to :meth:`~asyncio.StreamWriter.get_extra_info`, AnyIO offers a system of typed attributes where stream
classes (and any kind of class, really) can offer such extra information in a type safe manner. This is
especially useful with stream wrappers such as :class:`~.streams.tls.TLSStream`. Stream wrapper
classes like that can pass through any typed attributes from the wrapped stream while adding their own on top. They can
also choose to just override any attributes they like, all the while preserving type safety.

.. seealso:: :doc:`typedattrs`

Design problems with the thread API
+++++++++++++++++++++++++++++++++++

Asyncio comes with two ways to call blocking code in worker threads, each with its own caveats:

#. :func:`asyncio.to_thread`
#. :meth:`asyncio.loop.run_in_executor`

The first function is the more modern one, and supports :mod:`contextvar <contextvars>` propagation. However, there is
no way to use it with a thread pool executor other than the default. And due to the design decision of allowing the
pass-through of arbitrary positional and keyword arguments, no such option can ever be added without breaking backwards
compatibility. The second function, on the other hand, allows for explicitly specifying a thread pool to use, but it
doesn't support context variable propagation.

Another inconvenience comes from the inability to synchronously call synchronous functions in the event loop thread from
a worker thread. That is, running a synchronous function in the event loop thread and then returning its return value
from that call. While asyncio provides a way to do this for coroutine functions
(:func:`~asyncio.run_coroutine_threadsafe`), there is no counterpart for synchronous functions. The closest match would
be :meth:`~asyncio.loop.call_soon_threadsafe`, this function only schedules a callback to be run on the event loop
thread and does not provide any means to retrieve the return value.

How does AnyIO fix these problems?
----------------------------------

AnyIO uses its own thread pooling mechanism, based on :ref:`capacity limiters <capacity-limiters>` which are similar to
semaphores. To call a function in a worker thread, you would use :func:`.to_thread.run_sync`. This function can be
passed a specific capacity limiter to count against. All worker threads will be spawned in a thread pool specific to the
current event loop, and can be reused in any call to :func:`.to_thread.run_sync`, regardless of the capacity limiter
used. More worker threads will be spawned as necessary, so long as the capacity limiter allows it. The event loop's
thread pool is homogeneous, meaning idle threads in it are reused regardless of which capacity limiter was passed to the
call that spawned them.

.. note:: :func:`anyio.to_thread.run_sync` propagates context variables just like :func:`asyncio.to_thread`.

From inside AnyIO worker threads, you can call functions in the event loop thread using :func:`.from_thread.run` and
:func:`.from_thread.run_sync`, for coroutine functions and synchronous functions, respectively. The former is a direct
counterpart to asyncio's :func:`~asyncio.run_coroutine_threadsafe`, but the latter will wait for the function to run and
return its return value, unlike :meth:`~asyncio.loop.call_soon_threadsafe`.

Design problems with signal handling APIs
+++++++++++++++++++++++++++++++++++++++++

Asyncio only provides facilities to set or remove signal handlers. The :meth:`~asyncio.loop.add_signal_handler` method
will replace any existing handler for that signal, and won't return the previous handler for potential chaining. There
is also no way to get the current handler for a signal.

AnyIO provides an alternate mechanism to handle signals with its :func:`open_signal_receiver` context manager.

.. seealso:: :doc:`signals`

Missing file I/O and async path support
+++++++++++++++++++++++++++++++++++++++

Asyncio contains no facilities to help with file I/O, forcing you to use :func:`~asyncio.to_thread` or
:meth:`~asyncio.loop.run_in_executor` with every single file operation to prevent blocking the event loop thread.

To overcome this shortcoming, users often turn to libraries such as aiofiles_ and aiopath_ which offer async interfaces
for file and path access. However, AnyIO provides its own set of async file I/O APIs, including an async compatible
counterpart for the :class:`~pathlib.Path` class. Additionally, it should be noted that AnyIO provides
:ref:`file streams <FileStreams>` compatible with its stream class hierarchy.

.. seealso:: :doc:`fileio`

.. _aiofiles: https://github.com/Tinche/aiofiles
.. _aiopath: https://github.com/alexdelorenzo/aiopath

Features not in asyncio which you might be interested in
++++++++++++++++++++++++++++++++++++++++++++++++++++++++

AnyIO doesn't just offer replacements for asyncio APIs, but provides a bunch of its own conveniences which you may find
helpful.

Built-in pytest plugin
----------------------

AnyIO contains its own pytest_ plugin for running asynchronous tests. It can completely replace pytest-asyncio_ for
testing asynchronous code. It is somewhat simpler to use too, in addition to supporting more event loop implementations
such as Trio_.

.. seealso:: :doc:`testing`

.. _pytest: https://docs.pytest.org/
.. _pytest-asyncio: https://github.com/pytest-dev/pytest-asyncio

Connectables
------------

To complement its stream class hierarchy, AnyIO offers an abstraction for producing connected streams, either object or
bytes-oriented. This can be very useful when writing network clients, as abstracting out the connection mechanism allows
for a lot of customization, including mocking connections without having to resort to monkey patching.

.. seealso:: :ref:`connectables`

Context manager mix-in classes
------------------------------

AnyIO provides mix-in classes for safely implementing context managers which embed other context managers. Typically
this would require implementing ``__aenter__`` and ``__aexit__``, often requiring these classes to store state in the
instance and dealing with exceptions raised in ``__aenter__()``. The context manager mix-ins allow you to replace these
method pairs with a single method where you write your logic just like with
:func:`@asynccontextmanager <contextlib.asynccontextmanager>`, albeit at the cost of sacrificing re-entrancy.

.. seealso:: :doc:`contextmanagers`

.. _Trio: https://github.com/python-trio/trio
