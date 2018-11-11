Receiving operating system signals
==================================

You may occasionally find it useful to receive signals sent to your application in a meaningful
way. For example, when you receive a ``signal.SIGTERM`` signal, your application is expected to
shut down gracefully. Likewise, ``SIGHUP`` is often used as a means to ask the application to
reload its configuration.

AnyIO provides a simple mechanism for you to receive the signals you're interested in::

    import signal

    from anyio import receive_signals, run


    async def main():
        async with receive_signals(signal.SIGTERM, signal.SIGHUP) as signals:
            async for signum in signals:
                if signum == signal.SIGTERM:
                    return
                elif signum == signal.SIGHUP:
                    print('Reloading configuration')

    run(main)

.. note:: Windows does not natively support signals so do not rely on this in a cross platform
    application.
