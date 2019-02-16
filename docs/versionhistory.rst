Version history
===============

This library adheres to `Semantic Versioning <http://semver.org/>`_.

**UNRELEASED**

- Fixed ``setsockopt()`` passing options to the underlying method in the wrong manner

**1.0.0b2**

- Added introspection of running tasks via ``anyio.get_running_tasks()``
- Added the ``getsockopt()`` and ``setsockopt()`` methods to the ``SocketStream`` API
- Fixed mishandling of large buffers by ``BaseSocket.sendall()``
- Fixed compatibility with (and upgraded minimum required version to) trio v0.11

**1.0.0b1**

- Initial release
