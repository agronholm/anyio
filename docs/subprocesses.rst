Using subprocesses
==================

.. py:currentmodule:: anyio

AnyIO allows you to run arbitrary executables in subprocesses, either as a one-shot call
or by opening a process handle for you that gives you more control over the subprocess.

You can either give the command as a string, in which case it is passed to your default
shell (equivalent to ``shell=True`` in :func:`subprocess.run`), or as a sequence of
strings (``shell=False``) in which case the executable is the first item in the sequence
and the rest are arguments passed to it.

Running one-shot commands
-------------------------

To run an external command with one call, use :func:`~run_process`::

    from anyio import run_process, run


    async def main():
        result = await run_process('ps')
        print(result.stdout.decode())

    run(main)

The snippet above runs the ``ps`` command within a shell. To run it directly::

    from anyio import run_process, run


    async def main():
        result = await run_process(['ps'])
        print(result.stdout.decode())

    run(main)

Working with processes
----------------------

When you have more complex requirements for your interaction with subprocesses, you can
launch one with :func:`~open_process`::

    from anyio import open_process, run
    from anyio.streams.text import TextReceiveStream


    async def main():
        async with await open_process(['ps']) as process:
            async for text in TextReceiveStream(process.stdout):
                print(text)

    run(main)

See the API documentation of :class:`~.abc.Process` for more information.

.. _RunInProcess:

Running functions in worker processes
-------------------------------------

When you need to run CPU intensive code, worker processes are better than threads
because, with the exception of the experimental free-threaded builds of Python 3.13 and
later, current implementations of Python cannot run Python code in multiple threads at
once.

Exceptions to this rule are:

#. Blocking I/O operations
#. C extension code that explicitly releases the Global Interpreter Lock
#. :doc:`Subinterpreter workers <subinterpreters>`
   (experimental; available on Python 3.13 and later)

If the code you wish to run does not belong in this category, it's best to use worker
processes instead in order to take advantage of multiple CPU cores.
This is done by using :func:`.to_process.run_sync`::

    import time

    from anyio import run, to_process


    def cpu_intensive_function(arg1, arg2):
        time.sleep(1)
        return arg1 + arg2

    async def main():
        result = await to_process.run_sync(cpu_intensive_function, 'Hello, ', 'world!')
        print(result)

    # This check is important when the application uses to_process.run_sync()
    if __name__ == '__main__':
        run(main)

Any keyword argument to :func:`.to_process.run_sync` (other than ``cancellable`` and
``limiter``) will be passed to :class:`subprocess.Popen`, but note that in this case
a new subprocess will always be created, as it would not be possible to reuse a worker
process created with different keyword arguments. For instance, the following example
works (on Linux) because ``close_fds=False`` is passed::

  import os
  from functools import partial

  from anyio import create_task_group, run, to_process, to_thread


  def cpu_intensive_function(receiver, sender):
      data = os.read(receiver, 1024)
      os.write(sender, data + b", World!")

  async def main():
      receiver0, sender0 = os.pipe()
      receiver1, sender1 = os.pipe()
      os.set_inheritable(receiver0, True)
      os.set_inheritable(sender1, True)
      async with create_task_group() as tg:
          tg.start_soon(partial(to_process.run_sync, cpu_intensive_function, receiver0, sender1, close_fds=False))
          os.write(sender0, b"Hello")
          data = await to_thread.run_sync(os.read, receiver1, 1024)
      print(data)  # b'Hello, World!'

  # This check is important when the application uses to_process.run_sync()
  if __name__ == '__main__':
      run(main)

Technical details
*****************

There are some limitations regarding the arguments and return values passed:

* the arguments must be pickleable (using the highest available protocol)
* the return value must be pickleable (using the highest available protocol)
* the target callable must be importable (lambdas and inner functions won't work)

Other considerations:

* Even ``cancellable=False`` runs can be cancelled before the request has been sent to
  the worker process
* If a cancellable call is cancelled during execution on the worker process, the worker
  process will be killed
* The worker process imports the parent's ``__main__`` module, so guarding for any
  import time side effects using ``if __name__ == '__main__':`` is required to avoid
  infinite recursion
* ``sys.stdin`` and ``sys.stdout``, ``sys.stderr`` are redirected to ``/dev/null`` so
  :func:`print` and :func:`input` won't work
* Worker processes terminate after 5 minutes of inactivity, or when the event loop is
  finished

  * On asyncio, either :func:`asyncio.run` or :func:`anyio.run` must be used for proper
    cleanup to happen
* Multiprocessing-style synchronization primitives are currently not available
