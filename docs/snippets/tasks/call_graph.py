import asyncio

from anyio import create_task_group


async def foo(level: int = 0) -> None:
    if level == 3:
        asyncio.print_call_graph(asyncio.current_task())
        return

    async with create_task_group() as tg:
        tg.start_soon(foo, level + 1, name=f"Nesting level {level + 1}")


asyncio.run(foo())
