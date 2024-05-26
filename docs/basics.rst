The basics
==========

.. py:currentmodule:: anyio

AnyIO requires Python 3.8 or later to run. It is recommended that you set up a
virtualenv_ when developing or playing around with AnyIO.

Installation
------------

To install AnyIO, run:

.. code-block:: bash

    pip install anyio

To install a supported version of Trio_, you can install it as an extra like this:

.. code-block:: bash

    pip install anyio[trio]

Running async programs
----------------------

The simplest possible AnyIO program looks like this::

    from anyio import run


    async def main():
        print('Hello, world!')

    run(main)

This will run the program above on the default backend (asyncio). To run it on another
supported backend, say Trio_, you can use the ``backend`` argument, like so::

    run(main, backend='trio')

But AnyIO code is not required to be run via :func:`run`. You can just as well use the
native ``run()`` function of the backend library::

    import sniffio
    import trio
    from anyio import sleep


    async def main():
        print('Hello')
        await sleep(1)
        print("I'm running on", sniffio.current_async_library())

    trio.run(main)

Unless you're using trio-asyncio_, you will probably want to reduce the overhead caused
by dynamic backend detection by setting the ``ANYIO_LOCK_DETECTED_BACKEND`` environment
variable to ``1``. This makes AnyIO assume that whichever backend is detected on the
first AnyIO call will always be used going forward. This will not adversely affect the
pytest plugin, as AnyIO detects its presence and then disables backend locking.

.. versionchanged:: 4.0.0
    On the ``asyncio`` backend, ``anyio.run()`` now uses a back-ported version of
    :class:`asyncio.Runner` on Pythons older than 3.11.

.. versionchanged:: 4.4.0
    Added support for locking in the first detected backend via
    ``ANYIO_LOCK_DETECTED_BACKEND``

.. _trio-asyncio: https://github.com/python-trio/trio-asyncio

.. _backend options:

Backend specific options
------------------------

**Asyncio**:

* options covered in the documentation of :class:`asyncio.Runner`
* ``use_uvloop`` (``bool``, default=False): Use the faster uvloop_ event loop
  implementation, if available (this is a shorthand for passing
  ``loop_factory=uvloop.new_event_loop``, and is ignored if ``loop_factory`` is passed
  a value other than ``None``)

**Trio**: options covered in the
`official documentation
<https://trio.readthedocs.io/en/stable/reference-core.html#trio.run>`_

.. versionchanged:: 3.2.0
    The default value of ``use_uvloop`` was changed to ``False``.
.. versionchanged:: 4.0.0
    The ``policy`` option was replaced with ``loop_factory``.

.. _uvloop: https://pypi.org/project/uvloop/

Using native async libraries
----------------------------

AnyIO lets you mix and match code written for AnyIO and code written for the
asynchronous framework of your choice. There are a few rules to keep in mind however:

* You can only use "native" libraries for the backend you're running, so you cannot, for
  example, use a library written for Trio_ together with a library written for asyncio.
* Tasks spawned by these "native" libraries on backends other than Trio_ are not subject
  to the cancellation rules enforced by AnyIO
* Threads spawned outside of AnyIO cannot use :func:`.from_thread.run` to call
  asynchronous code

.. _virtualenv: https://docs.python-guide.org/dev/virtualenvs/
.. _Trio: https://github.com/python-trio/trio
