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

To run an external command with one call, use :func:`~run_process`:

.. literalinclude:: snippets/subprocesses/run_process.py

The snippet above runs the ``ps`` command within a shell. To run it directly:

.. literalinclude:: snippets/subprocesses/run_process_shell.py

Running a process in a task group
---------------------------------

Use :meth:`~.abc.TaskGroup.start` with :func:`run_process` to run a subprocess in the
background. It returns a :class:`~.abc.Process` once the process has been spawned and its
pipes have been set up. This does not mean that the program has finished initializing.
The task group waits for the subprocess to finish, and cancelling the task group stops
the subprocess and waits for it to exit.

.. literalinclude:: snippets/subprocesses/start_process.py

The ``input``, ``stdout``, ``stderr`` and ``check`` arguments behave the same as with a
direct call to :func:`run_process`. Standard output and error are captured by default;
the caller must not read those pipes itself. Use ``stdout=None`` and ``stderr=None`` to
inherit the parent's output streams. With ``check=True``, a nonzero exit status raises
:exc:`~subprocess.CalledProcessError` in the task group, including the captured output.
With ``stdin=subprocess.PIPE`` and no ``input`` argument, the caller can write to
:attr:`~.abc.Process.stdin` as shown above.

Customizing process cancellation
--------------------------------

By default, cancelling :func:`run_process` kills the subprocess immediately. To allow
the child to clean up first, pass an async callable as ``deliver_cancel``. It receives
the :class:`~.abc.Process` and runs shielded from external cancellation. It can send a
signal or a shutdown request using the child's own protocol. For example, this callback
allows up to five seconds after :meth:`~.abc.Process.terminate` before killing the child:

.. literalinclude:: snippets/subprocesses/deliver_cancel.py

The callback must arrange for the subprocess to exit. Returning from the callback does
not end the wait for the subprocess. Once the subprocess exits, the callback is cancelled
if it is still running. Standard output and error continue to be drained during shutdown
so the child can flush them. If the callback raises an exception, the subprocess is
killed and waited for, and the exception is propagated.

Working with processes
----------------------

When you have more complex requirements for your interaction with subprocesses, you can
launch one with :func:`~open_process`:

.. literalinclude:: snippets/subprocesses/open_process.py

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
This is done by using :func:`.to_process.run_sync`:

.. literalinclude:: snippets/subprocesses/run_in_worker_process.py

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
