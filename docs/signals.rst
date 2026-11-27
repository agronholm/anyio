Receiving operating system signals
==================================

.. py:currentmodule:: anyio

You may occasionally find it useful to receive signals sent to your application in a
meaningful way. For example, when you receive a ``signal.SIGTERM`` signal, your
application is expected to shut down gracefully. Likewise, ``SIGHUP`` is often used as a
means to ask the application to reload its configuration.

AnyIO provides a simple mechanism for you to receive the signals you're interested in:

.. literalinclude:: snippets/signals/receive_signals.py

When the context manager exits, it restores any Python signal handlers previously
installed with :func:`signal.signal`.

.. note:: Signal handlers can only be installed in the main thread, so they will not
   work when the event loop is being run through :class:`~.from_thread.BlockingPortal`,
   for instance.

.. note:: Windows does not natively support signals so do not rely on this in a cross
   platform application.

Handling KeyboardInterrupt and SystemExit
-----------------------------------------

By default, different backends handle the Ctrl+C (or Ctrl+Break on Windows) key
combination and external termination (:exc:`KeyboardInterrupt` and :exc:`SystemExit`,
respectively) differently: Trio raises the relevant exception inside the application
while asyncio shuts down all the tasks and exits. If you need to do your own cleanup in
these situations, you will need to install a signal handler:

.. literalinclude:: snippets/signals/handle_keyboard_interrupt.py

.. note:: Windows does not support the :data:`~signal.SIGTERM` signal so if you need a
   mechanism for graceful shutdown on Windows, you will have to find another way.
