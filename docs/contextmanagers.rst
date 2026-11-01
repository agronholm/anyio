Context manager mix-in classes
==============================

.. py:currentmodule:: anyio

Python classes that want to offer context management functionality normally implement
``__enter__()`` and ``__exit__()`` (for synchronous context managers) or
``__aenter__()`` and ``__aexit__()`` (for asynchronous context managers). While this
offers precise control and re-entrancy support, embedding *other* context managers in
this logic can be very error prone. To make this easier, AnyIO provides two context
manager mix-in classes, :class:`ContextManagerMixin` and
:class:`AsyncContextManagerMixin`. These classes provide implementations of
``__enter__()``, ``__exit__()`` or ``__aenter__()``, and ``__aexit__()``, that provide
another way to implement context managers similar to
:func:`@contextmanager <contextlib.contextmanager>` and
:func:`@asynccontextmanager <contextlib.asynccontextmanager>` - a generator-based
approach where the ``yield`` statement signals that the context has been entered.

Here's a trivial example of how to use the mix-in classes:

.. tabs::

   .. tab:: Synchronous

      .. literalinclude:: snippets/contextmanagers/mixin_sync.py

   .. tab:: Asynchronous

      .. literalinclude:: snippets/contextmanagers/mixin_async.py

When should I use the contextmanager mix-in classes?
----------------------------------------------------

When embedding other context managers, a common mistake is forgetting about error
handling when entering the context. Consider this example:

.. literalinclude:: snippets/contextmanagers/broken_context_manager.py

It's easy to think that you have everything covered with ``__aexit__()`` here, but what
if something goes wrong in ``__aenter__()``?  The ``__aexit__()`` method will never be
called.

The mix-in classes solve this problem by providing a robust implementation of
``__enter__()``/``__exit__()`` or ``__aenter__()``/``__aexit__()`` that handles errors
correctly. Thus, the above code should be written as:

.. literalinclude:: snippets/contextmanagers/better_context_manager.py

.. seealso:: :ref:`cancel_scope_stack_corruption`

Inheriting context manager classes
----------------------------------

Here's how you would call the superclass implementation from a subclass:

.. tabs::

   .. tab:: Synchronous

      .. literalinclude:: snippets/contextmanagers/inheritance_sync.py

   .. tab:: Asynchronous

      .. literalinclude:: snippets/contextmanagers/inheritance_async.py
