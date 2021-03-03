import pytest

from anyio import create_task_group
from anyio.lowlevel import cancel_shielded_checkpoint, checkpoint, checkpoint_if_cancelled

pytestmark = pytest.mark.anyio


@pytest.mark.parametrize('cancel', [False, True])
async def test_checkpoint_if_cancelled(cancel):
    async def func():
        nonlocal finished
        tg.spawn(second_func)
        if cancel:
            tg.cancel_scope.cancel()

        await checkpoint_if_cancelled()
        finished = True

    async def second_func():
        nonlocal second_finished
        assert finished != cancel
        second_finished = True

    finished = second_finished = False
    async with create_task_group() as tg:
        tg.spawn(func)

    assert finished != cancel
    assert second_finished


@pytest.mark.parametrize('cancel', [False, True])
async def test_cancel_shielded_checkpoint(cancel):
    async def func():
        nonlocal finished
        await cancel_shielded_checkpoint()
        finished = True

    async def second_func():
        nonlocal second_finished
        assert not finished
        second_finished = True

    finished = second_finished = False
    async with create_task_group() as tg:
        tg.spawn(func)
        tg.spawn(second_func)
        if cancel:
            tg.cancel_scope.cancel()

    assert finished
    assert second_finished


@pytest.mark.parametrize('cancel', [False, True])
async def test_checkpoint(cancel):
    async def func():
        nonlocal finished
        await checkpoint()
        finished = True

    async def second_func():
        nonlocal second_finished
        assert not finished
        second_finished = True

    finished = second_finished = False
    async with create_task_group() as tg:
        tg.spawn(func)
        tg.spawn(second_func)
        if cancel:
            tg.cancel_scope.cancel()

    assert finished != cancel
    assert second_finished
