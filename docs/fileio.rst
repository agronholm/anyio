Asynchronous file I/O support
=============================

.. py:currentmodule:: anyio

AnyIO provides asynchronous wrappers for blocking file operations. These wrappers run blocking
operations in worker threads.

Example::

    from anyio import open_file, run


    async def main():
        async with await open_file('/some/path/somewhere') as f:
            contents = await f.read()
            print(contents)

    run(main)

The wrappers also support asynchronous iteration of the file line by line, just as the standard
file objects support synchronous iteration::

    from anyio import open_file, run


    async def main():
        async with await open_file('/some/path/somewhere') as f:
            async for line in f:
                print(line, end='')

    run(main)

.. seealso:: :ref:`FileStreams`

Asynchronous path operations
----------------------------

AnyIO provides an asynchronous version of the :class:`pathlib.Path` class. It differs with the
original in a number of ways:

* Operations that perform disk I/O (like :meth:`~pathlib.Path.read_bytes``) are run in a worker
  thread and thus require an ``await``
* Methods like :meth:`~pathlib.Path.glob` return an asynchronous iterator that yields asynchronous
  :class:`~.Path` objects
* The ``parents`` property returns a sequence of :class:`~.Path` objects, and not
  :class:`pathlib.Path` objects like its trio counterpart
