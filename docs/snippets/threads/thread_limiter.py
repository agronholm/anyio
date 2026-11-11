from anyio import to_thread


async def foo() -> None:
    # Set the maximum number of worker threads to 60
    to_thread.current_default_thread_limiter().total_tokens = 60
