.. image:: https://travis-ci.com/agronholm/anyio.svg?branch=master
  :target: https://travis-ci.com/agronholm/anyio
  :alt: Build Status

AnyIO is a asynchronous compatibility API that allows applications and libraries written against
it to run unmodified on asyncio_, curio_ and trio_.

It bridges the following functionality:

* Task groups
* Cancellation
* Threads
* Signal handling
* Asynchronous file I/O
* Synchronization primitives (locks, conditions, events, semaphores, queues)
* High level networking (TCP, UDP and UNIX sockets)

.. _asyncio: https://docs.python.org/3/library/asyncio.html
.. _curio: https://github.com/dabeaz/curio
.. _trio: https://github.com/python-trio/trio
