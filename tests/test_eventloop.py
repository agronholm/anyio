import math
import sys

import pytest

from anyio import sleep_forever, sleep_until

if sys.version_info < (3, 8):
    from mock import AsyncMock
else:
    from unittest.mock import AsyncMock

pytestmark = pytest.mark.anyio
fake_current_time = 1620581544.0


@pytest.fixture
def fake_sleep(mocker):
    mocker.patch('anyio._core._eventloop.current_time', return_value=fake_current_time)
    return mocker.patch('anyio._core._eventloop.sleep', AsyncMock())


async def test_sleep_until(fake_sleep):
    sleep_time = 500.102352
    deadline = fake_current_time + sleep_time
    mock = AsyncMock()
    await mock()
    mock.assert_called_once()
    await sleep_until(deadline)
    fake_sleep.assert_called_once_with(pytest.approx(sleep_time))


async def test_sleep_until_in_past(fake_sleep):
    sleep_time = 500.102352
    deadline = fake_current_time - sleep_time
    await sleep_until(deadline)
    fake_sleep.assert_called_once_with(0)


async def test_sleep_forever(fake_sleep):
    await sleep_forever()
    fake_sleep.assert_called_once_with(math.inf)
