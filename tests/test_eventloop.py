import math
import sys

import pytest
from pytest_mock.plugin import MockerFixture

from anyio import sleep_forever, sleep_until

if sys.version_info < (3, 8):
    from mock import AsyncMock
else:
    from unittest.mock import AsyncMock

pytestmark = pytest.mark.anyio
fake_current_time = 1620581544.0


@pytest.fixture
def fake_sleep(mocker: MockerFixture) -> AsyncMock:
    mocker.patch('anyio._core._eventloop.current_time', return_value=fake_current_time)
    return mocker.patch('anyio._core._eventloop.sleep', AsyncMock())


async def test_sleep_until(fake_sleep: AsyncMock) -> None:
    deadline = fake_current_time + 500.102352
    await sleep_until(deadline)
    fake_sleep.assert_called_once_with(deadline - fake_current_time)


async def test_sleep_until_in_past(fake_sleep: AsyncMock) -> None:
    deadline = fake_current_time - 500.102352
    await sleep_until(deadline)
    fake_sleep.assert_called_once_with(0)


async def test_sleep_forever(fake_sleep: AsyncMock) -> None:
    await sleep_forever()
    fake_sleep.assert_called_once_with(math.inf)
