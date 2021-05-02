import pytest

from anyio import current_time, sleep_until

pytestmark = pytest.mark.anyio


async def test_sleep_until():
    deadline = current_time() + 0.05
    await sleep_until(deadline)
    assert current_time() >= deadline
