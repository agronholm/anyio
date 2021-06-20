The basics
==========

.. py:currentmodule:: anyio

AnyIO requires Python 3.6.2 or later to run. It is recommended that you set up a virtualenv_ when
developing or playing around with AnyIO.

Installation
------------

To install AnyIO, run:

.. code-block:: bash

    pip install anyio

To install a supported version of trio_, you can install it as an extra like this:

.. code-block:: bash

    pip install anyio[trio]

Running async programs
----------------------

The simplest possible AnyIO program looks like this::

    from anyio import run


    async def main():
        print('Hello, world!')

    run(main)

This will run the program above on the default backend (asyncio). To run it on another supported
backend, say trio_, you can use the ``backend`` argument, like so::

    run(main, backend='trio')

But AnyIO code is not required to be run via :func:`run`. You can just as well use the native
``run()`` function of the backend library::

    import sniffio
    import trio
    from anyio import sleep


    async def main():
        print('Hello')
        await sleep(1)
        print("I'm running on", sniffio.current_async_library())

    trio.run(main)

.. _backend options:

Backend specific options
------------------------

Asyncio:

* ``debug`` (``bool``, default=False): Enables `debug mode`_ in the event loop
* ``use_uvloop`` (``bool``, default=False): Use the faster uvloop_ event loop implementation, if
  available
* ``policy`` (``AbstractEventLoopPolicy``, default=None): the event loop policy instance to use
  for creating a new event loop (overrides ``use_uvloop``)

Trio: options covered in the
`official documentation <https://trio.readthedocs.io/en/stable/reference-core.html#trio.run>`_

.. note:: The default value of ``use_uvloop`` was ``True`` before v3.2.0.

.. _debug mode: https://docs.python.org/3/library/asyncio-eventloop.html#enabling-debug-mode
.. _uvloop: https://pypi.org/project/uvloop/

Using native async libraries
----------------------------

AnyIO lets you mix and match code written for AnyIO and code written for the asynchronous framework
of your choice. There are a few rules to keep in mind however:

* You can only use "native" libraries for the backend you're running, so you cannot, for example,
  use a library written for trio together with a library written for asyncio.
* Tasks spawned by these "native" libraries on backends other than trio_ are not subject to the
  cancellation rules enforced by AnyIO
* Threads spawned outside of AnyIO cannot use :func:`.from_thread.run` to call asynchronous code

.. _virtualenv: https://docs.python-guide.org/dev/virtualenvs/
.. _trio: https://github.com/python-trio/trio
