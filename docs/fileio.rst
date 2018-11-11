Asynchronous file I/O support
=============================

AnyIO provides asynchronous wrappers for blocking file operations. These wrappers run blocking
operations in worker threads.

Example::

    from anyio import aopen, run


    async def main():
        async with await aopen('/some/path/somewhere') as f:
            contents = await f.read()
            print(contents)

    run(main)

The wrappers also support asynchronous iteration of the file line by line, just as the standard
file objects support synchronous iteration::

    from anyio import aopen, run


    async def main():
        async with await aopen('/some/path/somewhere') as f:
            async for line in f:
                print(line, end='')

    run(main)
