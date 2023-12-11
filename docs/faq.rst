Frequently Asked Questions
==========================

Why is Curio not supported as a backend?
----------------------------------------

Curio_ was supported in AnyIO before v3.0. Support for it was dropped for two reasons:

#. Its interface allowed only coroutine functions to access the Curio_ kernel. This
   forced AnyIO to follow suit in its own API design, making it difficult to adapt
   existing applications that relied on synchronous callbacks to use AnyIO. It also
   interfered with the goal of matching Trio's API in functions with the same purpose
   (e.g. ``Event.set()``).
#. The maintainer specifically requested Curio_ support to be removed from AnyIO
   (`issue 185 <https://github.com/agronholm/anyio/issues/185>`_).

.. _Curio: https://github.com/dabeaz/curio

Why is Twisted not supported as a backend?
------------------------------------------

The minimum requirement to support Twisted_ would be for sniffio_ to be able to detect a
running Twisted event loop (and be able to tell when Twisted_ is being run on top of its
asyncio reactor). This is not currently supported in sniffio_, so AnyIO cannot support
Twisted either.

There is a Twisted `issue <https://github.com/twisted/twisted/pull/1263>`_ that you can
follow if you're interested in Twisted support in AnyIO.

.. _Twisted: https://twistedmatrix.com/trac/
.. _sniffio: https://github.com/python-trio/sniffio
