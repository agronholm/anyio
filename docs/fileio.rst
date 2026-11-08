Asynchronous file I/O support
=============================

.. py:currentmodule:: anyio

AnyIO provides asynchronous wrappers for blocking file operations. These wrappers run
blocking operations in worker threads.

Example:

.. literalinclude:: snippets/fileio/read_file.py

The wrappers also support asynchronous iteration of the file line by line, just as the
standard file objects support synchronous iteration:

.. literalinclude:: snippets/fileio/iterate_lines.py

To wrap an existing open file object as an asynchronous file, you can use
:func:`.wrap_file`:

.. literalinclude:: snippets/fileio/wrap_file.py

.. note:: Closing the wrapper also closes the underlying synchronous file object.

.. seealso:: :ref:`FileStreams`

Asynchronous path operations
----------------------------

AnyIO provides an asynchronous version of the :class:`pathlib.Path` class. It differs
with the original in a number of ways:

* Operations that perform disk I/O (like :meth:`~pathlib.Path.read_bytes`) are run in a
  worker thread and thus require an ``await``
* Methods like :meth:`~pathlib.Path.glob` return an asynchronous iterator that yields
  asynchronous :class:`~.Path` objects
* Properties and methods that normally return :class:`pathlib.Path` objects return
  :class:`~.Path` objects instead
* Methods and properties from the Python 3.10 API are available on all versions
* Use as a context manager is not supported, as it is deprecated in pathlib

For example, to create a file with binary content:

.. literalinclude:: snippets/fileio/path_write_bytes.py

Asynchronously iterating a directory contents can be done as follows:

.. literalinclude:: snippets/fileio/path_iterdir.py

Limiting concurrency
--------------------

By default, all file I/O operations use the default capacity limiter. If you wish to
more explicitly control the concurrency, you can pass a custom :class:`CapacityLimiter`
to :func:`open_file`, :func:`wrap_file` or :class:`Path` (or its various class
methods):

.. literalinclude:: snippets/fileio/limit_concurrency.py
