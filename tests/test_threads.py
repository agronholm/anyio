import pytest

from hyperio import run_async_from_thread, run_in_thread, is_in_event_loop_thread


@pytest.mark.hyperio
async def test_run_async_from_thread():
    async def add(a, b):
        assert is_in_event_loop_thread()
        return a + b

    def worker(a, b):
        assert not is_in_event_loop_thread()
        return run_async_from_thread(add, a, b)

    result = await run_in_thread(worker, 1, 2)
    assert result == 3
