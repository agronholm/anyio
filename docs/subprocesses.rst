Using subprocesses
==================

.. py:currentmodule:: anyio

AnyIO allows you to run arbitrary executables in subprocesses, either as a one-shot call or by
opening a process handle for you that gives you more control over the subprocess.

You can either give the command as a string, in which case it is passed to your default shell
(equivalent to ``shell=True`` in :func:`subprocess.run`), or as a sequence of strings
(``shell=False``) in which the executable is the first item in the sequence and the rest are
arguments passed to it.

.. note:: The subprocess facilities provided by AnyIO do not include a way to execute arbitrary
          Python code like the :mod:`multiprocessing` module does, but they can be used as
          building blocks for such a feature.

Running one-shot commands
-------------------------

To run an external command with one call, use :func:`~run_process`::

    from anyio import run_process, run


    async def main():
        result = await run_process('/usr/bin/ps')
        print(result.stdout.decode())

    run(main)

The snippet above runs the ``ps`` command within a shell (. To run it directly::

    from anyio import run_process, run


    async def main():
        result = await run_process(['/usr/bin/ps'])
        print(result.stdout.decode())

    run(main)

Working with processes
----------------------

When you have more complex requirements for your interaction with subprocesses, you can launch one
with :func:`~open_process`::

    from anyio import open_process, run
    from anyio.streams.text import TextReceiveStream


    async def main():
        async with await open_process(['/usr/bin/ps']) as process:
            for text in TextReceiveStream(process.stdout):
                print(text)

    run(main)

See the API documentation of :class:`~.abc.Process` for more information.
