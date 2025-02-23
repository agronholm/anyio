Asynchronous Temporary File and Directory
=========================================

.. py:currentmodule:: anyio

This module provides asynchronous wrappers for handling temporary files and directories
using the :mod:`tempfile` module. The asynchronous methods execute blocking operations in worker threads.

Temporary File
--------------

:class:`TemporaryFile` creates a temporary file that is automatically deleted upon closure.

**Example:**

.. code-block:: python

    from anyio import TemporaryFile, run

    async def main():
        async with TemporaryFile(mode="w+") as f:
            await f.write("Temporary file content")
            await f.seek(0)
            print(await f.read())  # Output: Temporary file content

    run(main)

Named Temporary File
--------------------

:class:`NamedTemporaryFile` works similarly to :class:`TemporaryFile`, but the file has a visible name in the filesystem.

**Example:**

.. code-block:: python

    from anyio import NamedTemporaryFile, run

    async def main():
        async with NamedTemporaryFile(mode="w+", delete=True) as f:
            print(f"Temporary file name: {f.name}")
            await f.write("Named temp file content")
            await f.seek(0)
            print(await f.read())

    run(main)

Spooled Temporary File
----------------------

:class:`SpooledTemporaryFile` is useful when temporary data is small and should be kept in memory rather than written to disk.

**Example:**

.. code-block:: python

    from anyio import SpooledTemporaryFile, run

    async def main():
        async with SpooledTemporaryFile(max_size=1024, mode="w+") as f:
            await f.write("Spooled temp file content")
            await f.seek(0)
            print(await f.read())

    run(main)

Temporary Directory
-------------------

The :class:`TemporaryDirectory` provides an asynchronous way to create temporary directories.

**Example:**

.. code-block:: python

    from anyio import TemporaryDirectory, run

    async def main():
        async with TemporaryDirectory() as temp_dir:
            print(f"Temporary directory path: {temp_dir}")

    run(main)

Low-Level Temporary File and Directory Creation
-----------------------------------------------

For more control, the module provides lower-level functions:

- :func:`mkstemp` - Creates a temporary file and returns a tuple of file descriptor and path.
- :func:`mkdtemp` - Creates a temporary directory and returns the directory path.
- :func:`gettempdir` - Returns the path of the default temporary directory.
- :func:`gettempdirb` - Returns the path of the default temporary directory in bytes.

**Example:**

.. code-block:: python

    from anyio import mkstemp, mkdtemp, gettempdir, run
    import os

    async def main():
        fd, path = await mkstemp(suffix=".txt", prefix="mkstemp_", text=True)
        print(f"Created temp file: {path}")

        temp_dir = await mkdtemp(prefix="mkdtemp_")
        print(f"Created temp dir: {temp_dir}")

        print(f"Default temp dir: {await gettempdir()}")

        os.remove(path)

    run(main)

.. note::
    Using these functions requires manual cleanup of the created files and directories.

.. seealso::

    - Python Standard Library: :mod:`tempfile` (`official documentation <https://docs.python.org/3/library/tempfile.html>`_)
