Fixed :meth:`~anyio.abc.UNIXSocketStream.send_fds` silently dropping socket objects
passed in ``fds`` instead of sending their file descriptors.
