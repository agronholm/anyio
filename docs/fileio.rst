Asynchronous file I/O support
=============================

.. py:currentmodule:: anyio

AnyIO provides asynchronous wrappers for blocking file operations. These wrappers run
blocking operations in worker threads.

Example::

    from anyio import open_file, run


    async def main():
        async with await open_file('/some/path/somewhere') as f:
            contents = await f.read()
            print(contents)

    run(main)

The wrappers also support asynchronous iteration of the file line by line, just as the
standard file objects support synchronous iteration::

    from anyio import open_file, run


    async def main():
        async with await open_file('/some/path/somewhere') as f:
            async for line in f:
                print(line, end='')

    run(main)

To wrap an existing open file object as an asynchronous file, you can use
:func:`.wrap_file`::

    from anyio import wrap_file, run


    async def main():
        with open('/some/path/somewhere') as f:
            async for line in wrap_file(f):
                print(line, end='')

    run(main)

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

For example, to create a file with binary content::

    from anyio import Path, run


    async def main():
        path = Path('/foo/bar')
        await path.write_bytes(b'hello, world')

    run(main)

Asynchronously iterating a directory contents can be done as follows::

    from anyio import Path, run


    async def main():
        # Print the contents of every file (assumed to be text) in the directory /foo/bar
        dir_path = Path('/foo/bar')
        async for path in dir_path.iterdir():
            if await path.is_file():
                print(await path.read_text())
                print('---------------------')

    run(main)
