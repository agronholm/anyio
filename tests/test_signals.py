from __future__ import annotations

import os
import signal
import sys
from collections.abc import AsyncIterable
from contextlib import nullcontext
from unittest.mock import Mock

import pytest

from anyio import create_task_group, fail_after, open_signal_receiver, to_thread

pytestmark = [
    pytest.mark.skipif(
        sys.platform == "win32",
        reason="Signal delivery cannot be tested on Windows",
    ),
    # Workaround for https://github.com/MagicStack/uvloop/issues/703
    pytest.mark.filterwarnings(
        "ignore:'asyncio.iscoroutinefunction' is deprecated:DeprecationWarning"
    ),
]


async def test_receive_signals() -> None:
    with open_signal_receiver(signal.SIGUSR1, signal.SIGUSR2) as sigiter:
        await to_thread.run_sync(os.kill, os.getpid(), signal.SIGUSR1)
        await to_thread.run_sync(os.kill, os.getpid(), signal.SIGUSR2)
        with fail_after(1):
            sigusr1 = await sigiter.__anext__()
            assert isinstance(sigusr1, signal.Signals)
            assert sigusr1 == signal.Signals.SIGUSR1

            sigusr2 = await sigiter.__anext__()
            assert isinstance(sigusr2, signal.Signals)
            assert sigusr2 == signal.Signals.SIGUSR2


async def test_task_group_cancellation_open() -> None:
    async def signal_handler() -> None:
        with open_signal_receiver(signal.SIGUSR1) as sigiter:
            async for _ in sigiter:
                pytest.fail("SIGUSR1 should not be sent")

            pytest.fail("signal_handler should have been cancelled")

        pytest.fail("open_signal_receiver should not suppress cancellation")

    async with create_task_group() as tg:
        tg.start_soon(signal_handler)
        tg.cancel_scope.cancel()


async def test_task_group_cancellation_consume() -> None:
    async def consume(sigiter: AsyncIterable[int]) -> None:
        async for _ in sigiter:
            pytest.fail("SIGUSR1 should not be sent")

        pytest.fail("consume should have been cancelled")

    with open_signal_receiver(signal.SIGUSR1) as sigiter:
        async with create_task_group() as tg:
            tg.start_soon(consume, sigiter)
            tg.cancel_scope.cancel()


@pytest.mark.parametrize(
    "handler",
    [signal.SIG_DFL, signal.SIG_IGN, None],
    ids=["default", "ignored", "custom"],
)
@pytest.mark.parametrize("raise_exc", [False, True], ids=["normal", "exception"])
async def test_restore_signal_handlers(
    handler: signal.Handlers | None, raise_exc: bool
) -> None:
    signals = (signal.SIGINT, signal.SIGUSR1)
    installed_handler = Mock() if handler is None else handler
    previous_handlers = {sig: signal.signal(sig, installed_handler) for sig in signals}
    try:
        with (
            pytest.raises(ValueError, match="test error")
            if raise_exc
            else nullcontext()
        ):
            with open_signal_receiver(*signals):
                if raise_exc:
                    raise ValueError("test error")

        for sig in signals:
            assert signal.getsignal(sig) == installed_handler
    finally:
        for sig, previous_handler in previous_handlers.items():
            signal.signal(sig, previous_handler)
