#!/usr/bin/env python3
"""
Example demonstrating the new configurable MAX_IDLE_TIME feature.

This example shows how to configure worker thread and process idle times
using the backend_options parameter.
"""

from __future__ import annotations

import asyncio
import time

from anyio import run, to_process, to_thread


async def worker_thread_task():
    """A task that runs in a worker thread."""
    print(f"Worker thread task started at {time.time()}")
    # Simulate some work
    await asyncio.sleep(1)
    print(f"Worker thread task completed at {time.time()}")
    return "thread_result"


async def worker_process_task():
    """A task that runs in a worker process."""
    import os

    print(f"Worker process task started in PID {os.getpid()} at {time.time()}")
    # Simulate some work
    time.sleep(1)
    print(f"Worker process task completed in PID {os.getpid()} at {time.time()}")
    return "process_result"


async def main():
    """Main function demonstrating the configuration options."""

    print("=== AnyIO Configurable MAX_IDLE_TIME Example ===\n")

    # Example 1: Default configuration (10s for threads, 300s for processes)
    print("1. Running with default configuration:")
    print("   - Worker thread max idle time: 10 seconds")
    print("   - Worker process max idle time: 300 seconds")

    result1 = await to_thread.run_sync(lambda: "default_thread")
    result2 = await to_process.run_sync(lambda: "default_process")

    print(f"   Results: {result1}, {result2}\n")

    # Example 2: Custom configuration with shorter idle times
    print("2. Running with custom configuration:")
    print("   - Worker thread max idle time: 5 seconds")
    print("   - Worker process max idle time: 60 seconds")

    # Note: In a real application, you would set these via backend_options
    # when calling anyio.run(). For this example, we'll demonstrate the
    # configuration API directly.
    from anyio._core._config import get_config

    config = get_config()
    original_thread_time = config.worker_thread_max_idle_time
    original_process_time = config.worker_process_max_idle_time

    try:
        config.worker_thread_max_idle_time = 5.0
        config.worker_process_max_idle_time = 60.0

        result3 = await to_thread.run_sync(lambda: "custom_thread")
        result4 = await to_process.run_sync(lambda: "custom_process")

        print(f"   Results: {result3}, {result4}\n")

    finally:
        # Restore original values
        config.worker_thread_max_idle_time = original_thread_time
        config.worker_process_max_idle_time = original_process_time

    # Example 3: Demonstrating the backend_options approach
    print("3. Running with backend_options (recommended approach):")

    async def demo_coroutine():
        result5 = await to_thread.run_sync(lambda: "backend_options_thread")
        result6 = await to_process.run_sync(lambda: "backend_options_process")
        return result5, result6

    # This is how you would use it in a real application
    results = run(
        demo_coroutine,
        backend_options={
            "worker_thread_max_idle_time": 15.0,
            "worker_process_max_idle_time": 120.0,
        },
    )

    print(f"   Results: {results}\n")

    print("=== Example completed ===")


if __name__ == "__main__":
    run(main)
