import sys

import pytest

import anyio
from anyio import (
    create_event, create_task_group, get_current_task, get_running_tasks, wait_all_tasks_blocked)

pytestmark = pytest.mark.anyio


def test_main_task_name(anyio_backend_name, anyio_backend_options):
    async def main():
        nonlocal task_name
        task_name = (await get_current_task()).name

    task_name = None
    anyio.run(main, backend=anyio_backend_name, backend_options=anyio_backend_options)
    assert task_name == 'test_debugging.test_main_task_name.<locals>.main'

    # Work around sniffio/asyncio bug that leaves behind an unclosed event loop
    if anyio_backend_name == 'asyncio':
        import asyncio
        import gc
        for loop in [obj for obj in gc.get_objects()
                     if isinstance(obj, asyncio.AbstractEventLoop)]:
            loop.close()


async def test_get_running_tasks():
    async def inspect():
        await wait_all_tasks_blocked()
        new_tasks = set(await get_running_tasks()) - existing_tasks
        task_infos[:] = sorted(new_tasks, key=lambda info: info.name or '')
        await event.set()

    event = create_event()
    task_infos = []
    host_task = await get_current_task()
    async with create_task_group() as tg:
        existing_tasks = set(await get_running_tasks())
        await tg.spawn(event.wait, name='task1')
        await tg.spawn(event.wait, name='task2')
        await tg.spawn(inspect)

    assert len(task_infos) == 3
    expected_names = ['task1', 'task2', 'test_debugging.test_get_running_tasks.<locals>.inspect']
    for task, expected_name in zip(task_infos, expected_names):
        assert task.parent_id == host_task.id
        assert task.name == expected_name
        assert repr(task) == f'TaskInfo(id={task.id}, name={expected_name!r})'


@pytest.mark.filterwarnings('ignore:"@coroutine" decorator is deprecated:DeprecationWarning')
def test_wait_generator_based_task_blocked():
    from asyncio import DefaultEventLoopPolicy, Event, coroutine, set_event_loop

    async def native_coro_part():
        await wait_all_tasks_blocked()
        assert not gen_task._coro.gi_running
        if sys.version_info < (3, 7):
            assert gen_task._coro.gi_yieldfrom.gi_code.co_name == 'wait'
        else:
            assert gen_task._coro.gi_yieldfrom.cr_code.co_name == 'wait'

        event.set()

    @coroutine
    def generator_part():
        yield from event.wait()

    loop = DefaultEventLoopPolicy().new_event_loop()
    try:
        set_event_loop(loop)
        event = Event()
        gen_task = loop.create_task(generator_part())
        loop.run_until_complete(native_coro_part())
    finally:
        set_event_loop(None)
        loop.close()
