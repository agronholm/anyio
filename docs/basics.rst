The basics
==========

AnyIO requires Python 3.5.3 or later to run. It is recommended that you set up a virtualenv_ when
developing or playing around with AnyIO.

Installation
------------

To install AnyIO, run:

.. code-block:: bash

    pip install anyio

To install a supported version of trio_ or curio_, you can use install them as extras like this:

.. code-block:: bash

    pip install anyio[curio]

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

But AnyIO code is not required to be run via :func:`anyio.run`. You can just as well use the native
``run()`` function of the backend library::

    import sniffio
    import trio
    from anyio import sleep


    async def main():
        print('Hello')
        await sleep(1)
        print("I'm running on", sniffio.current_async_library())

    trio.run(main)

Using native async libraries
----------------------------

AnyIO lets you mix and match code written for AnyIO and code written for the asynchronous framework
of your choice. There are a few rules to keep in mind however:

* You can only use "native" libraries for the backend you're running, so you cannot, for example,
  use a library written for trio together with a library written for asyncio.
* Tasks spawned by these "native" libraries on backends other than trio_ are not subject to the
  cancellation rules enforced by AnyIO
* Threads spawned outside of AnyIO cannot use :func:`~run_async_from_thread` to call asynchronous
  code

.. _virtualenv: https://docs.python-guide.org/dev/virtualenvs/
.. _trio: https://github.com/python-trio/trio
.. _curio: https://github.com/dabeaz/curio
