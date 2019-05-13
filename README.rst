.. image:: https://dev.azure.com/alexgronholm/anyio/_apis/build/status/agronholm.anyio?branchName=master
  :alt: Build Status
.. image:: https://img.shields.io/azure-devops/coverage/agronholm/anyio/1/master.svg
  :alt: Code Coverage
.. image:: https://readthedocs.org/projects/anyio/badge/?version=latest
  :target: https://anyio.readthedocs.io/en/latest/?badge=latest
  :alt: Documentation

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

You can even use it together with native libraries from your selected backend in applications.
Doing this in libraries is not advisable however since it limits the usefulness of your library.

AnyIO comes with its own pytest_ plugin which also supports asynchronous fixtures.
It even works with the popular Hypothesis_ library.

.. _asyncio: https://docs.python.org/3/library/asyncio.html
.. _curio: https://github.com/dabeaz/curio
.. _trio: https://github.com/python-trio/trio
.. _pytest: https://docs.pytest.org/en/latest/
.. _Hypothesis: https://hypothesis.works/
