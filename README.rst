.. image:: https://github.com/agronholm/anyio/workflows/Python%20codeqa/test/badge.svg?branch=master
  :target: https://github.com/agronholm/anyio/actions?query=workflow%3A%22Python+codeqa%2Ftest%22+branch%3Amaster
  :alt: Build Status
.. image:: https://coveralls.io/repos/github/agronholm/anyio/badge.svg?branch=master
  :target: https://coveralls.io/github/agronholm/anyio?branch=master
  :alt: Code Coverage
.. image:: https://readthedocs.org/projects/anyio/badge/?version=latest
  :target: https://anyio.readthedocs.io/en/latest/?badge=latest
  :alt: Documentation
.. image:: https://badges.gitter.im/gitterHQ/gitter.svg
  :target: https://gitter.im/python-trio/AnyIO
  :alt: Gitter chat

AnyIO is a asynchronous compatibility API that allows applications and libraries written against
it to run unmodified on asyncio_, curio_ and trio_.

It bridges the following functionality:

* Task groups
* Cancellation
* Threads
* Signal handling
* Asynchronous file I/O
* Subprocesses
* Inter-task synchronization and communication (locks, conditions, events, semaphores, object
  streams)
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
