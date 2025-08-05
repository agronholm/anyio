Backend Options
==============

AnyIO supports various configuration options that can be passed to the backend through the ``backend_options`` parameter when calling :func:`anyio.run()`.

Worker Thread Idle Time
----------------------

.. versionadded:: 4.0

The ``worker_thread_max_idle_time`` option controls how long worker threads in the thread pool can remain idle before being terminated. This is useful for applications that need to conserve resources or have specific timing requirements.

**Default value:** 10.0 seconds

**Example usage:**

.. code-block:: python

    import anyio

    async def my_coroutine():
        # Your async code here
        pass

    # Set worker thread max idle time to 30 seconds
    anyio.run(my_coroutine, backend_options={
        "worker_thread_max_idle_time": 30.0
    })

Worker Process Idle Time
-----------------------

.. versionadded:: 4.0

The ``worker_process_max_idle_time`` option controls how long worker processes in the process pool can remain idle before being terminated. This is particularly useful for applications that need to manage process lifecycle or have specific resource constraints.

**Default value:** 300.0 seconds (5 minutes)

**Example usage:**

.. code-block:: python

    import anyio

    async def my_coroutine():
        # Your async code here
        pass

    # Set worker process max idle time to 10 minutes
    anyio.run(my_coroutine, backend_options={
        "worker_process_max_idle_time": 600.0
    })

Use Cases
---------

These configuration options are particularly useful in the following scenarios:

1. **Django Applications**: When Django drops and recreates connections after workers are idle for more than a certain time, you can adjust the worker thread idle time to prevent this behavior.

2. **Resource-Constrained Environments**: In environments with limited memory or CPU resources, you may want to terminate idle workers more quickly to free up resources.

3. **High-Traffic Applications**: For applications with varying load patterns, you can tune the idle times to optimize resource usage during different periods.

4. **Containerized Environments**: In Docker or Kubernetes environments, you might want to adjust these values based on your container lifecycle management strategy.

Configuration Validation
-----------------------

Both configuration options must be positive numbers. Attempting to set negative or zero values will raise a :exc:`ValueError`.

.. code-block:: python

    import anyio

    # This will raise ValueError
    anyio.run(my_coroutine, backend_options={
        "worker_thread_max_idle_time": -1.0  # Invalid!
    })
