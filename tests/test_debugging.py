import pytest

from anyio import create_task_group, create_event, wait_all_tasks_blocked, get_running_tasks


@pytest.mark.anyio
async def test_get_running_tasks():
    event = create_event()
    async with create_task_group() as tg:
        existing_tasks = set(get_running_tasks())
        await tg.spawn(event.wait, name='task1')
        await tg.spawn(event.wait, name='task2')
        await wait_all_tasks_blocked()
        task_infos = set(get_running_tasks()) - existing_tasks
        await event.set()

    task_infos = sorted(task_infos, key=lambda info: info.name or '')
    assert len(task_infos) == 2
    assert task_infos[0].name == 'task1'
    assert task_infos[1].name == 'task2'
