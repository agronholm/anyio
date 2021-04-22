import pytest

from anyio import CancelScope, Sequencer, create_task_group, wait_all_tasks_blocked

pytestmark = pytest.mark.anyio


async def test_Sequencer():
    record = []

    def t(val):
        print(val)
        record.append(val)

    async def f1(seq):
        async with seq(1):
            t(("f1", 1))
        async with seq(3):
            t(("f1", 3))
        async with seq(4):
            t(("f1", 4))

    async def f2(seq):
        async with seq(0):
            t(("f2", 0))
        async with seq(2):
            t(("f2", 2))

    seq = Sequencer()
    async with create_task_group() as nursery:
        nursery.start_soon(f1, seq)
        nursery.start_soon(f2, seq)
        async with seq(5):
            await wait_all_tasks_blocked()
        assert record == [("f2", 0), ("f1", 1), ("f2", 2), ("f1", 3), ("f1", 4)]

    seq = Sequencer()
    # Catches us if we try to re-use a sequence point:
    async with seq(0):
        pass
    with pytest.raises(RuntimeError):
        async with seq(0):
            pass  # pragma: no cover


async def test_Sequencer_cancel():
    # Killing a blocked task makes everything blow up
    record = []
    seq = Sequencer()

    async def child(i):
        with CancelScope() as scope:
            if i == 1:
                scope.cancel()
            try:
                async with seq(i):
                    pass  # pragma: no cover
            except RuntimeError:
                record.append("seq({}) RuntimeError".format(i))

    async with create_task_group() as nursery:
        nursery.start_soon(child, 1)
        nursery.start_soon(child, 2)
        async with seq(0):
            pass  # pragma: no cover

    assert record == ["seq(1) RuntimeError", "seq(2) RuntimeError"]

    # Late arrivals also get errors
    with pytest.raises(RuntimeError):
        async with seq(3):
            pass  # pragma: no cover
