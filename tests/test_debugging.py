import pytest

from anyio import (
    create_task_group, create_event, wait_all_tasks_blocked, get_running_tasks, get_current_task)


@pytest.mark.anyio
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
        await tg.spawn(inspect, name='inspector')

    assert len(task_infos) == 3
    for task, expected_name in zip(task_infos, ['inspector', 'task1', 'task2']):
        assert task.parent_id == host_task.id
        assert task.name == expected_name
        assert repr(task) == "TaskInfo(id={}, name={!r})".format(task.id, expected_name)
