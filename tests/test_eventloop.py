from __future__ import annotations

import asyncio
import math
from asyncio import get_running_loop
from unittest.mock import AsyncMock

import pytest
from pytest import MonkeyPatch
from pytest_mock.plugin import MockerFixture

from anyio import run, sleep_forever, sleep_until

pytestmark = pytest.mark.anyio
fake_current_time = 1620581544.0


@pytest.fixture
def fake_sleep(mocker: MockerFixture) -> AsyncMock:
    mocker.patch("anyio._core._eventloop.current_time", return_value=fake_current_time)
    return mocker.patch("anyio._core._eventloop.sleep", AsyncMock())


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


def test_run_task() -> None:
    """Test that anyio.run() on asyncio will work with a callable returning a Future."""

    async def async_add(x: int, y: int) -> int:
        return x + y

    result = run(asyncio.create_task, async_add(1, 2), backend="asyncio")
    assert result == 3


class TestAsyncioOptions:
    def test_debug(self) -> None:
        async def main() -> bool:
            return get_running_loop().get_debug()

        debug = run(main, backend="asyncio", backend_options={"debug": True})
        assert debug is True

    def test_debug_via_env(self, monkeypatch: MonkeyPatch) -> None:
        async def main() -> bool:
            return get_running_loop().get_debug()

        monkeypatch.setenv("PYTHONASYNCIODEBUG", "1")
        debug = run(main, backend="asyncio")
        assert debug is True

    def test_loop_factory(self) -> None:
        async def main() -> type:
            return type(get_running_loop())

        uvloop = pytest.importorskip("uvloop", reason="uvloop not installed")
        loop_class = run(
            main,
            backend="asyncio",
            backend_options={"loop_factory": uvloop.new_event_loop},
        )
        assert issubclass(loop_class, uvloop.Loop)

    def test_use_uvloop(self) -> None:
        async def main() -> type:
            return type(get_running_loop())

        uvloop = pytest.importorskip("uvloop", reason="uvloop not installed")
        loop_class = run(main, backend="asyncio", backend_options={"use_uvloop": True})
        assert issubclass(loop_class, uvloop.Loop)
