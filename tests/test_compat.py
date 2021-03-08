import signal
import sys

import pytest

from anyio import (
    create_capacity_limiter, create_condition, create_event, create_lock, create_semaphore,
    create_task_group, fail_after, maybe_async, maybe_async_cm, move_on_after, open_cancel_scope,
    open_signal_receiver, sleep)

pytestmark = pytest.mark.anyio


async def test_maybe_async():
    with open_cancel_scope() as scope:
        await maybe_async(scope.cancel())


async def test_maybe_async_cm():
    async with maybe_async_cm(open_cancel_scope()):
        pass


class TestDeprecations:
    @pytest.mark.skipif(sys.platform == 'win32',
                        reason='Signal delivery cannot be tested on Windows')
    async def test_open_signal_receiver(self):
        with pytest.deprecated_call():
            async with open_signal_receiver(signal.SIGINT):
                pass

    async def test_cancelscope_cancel(self):
        with open_cancel_scope() as scope:
            with pytest.deprecated_call():
                await scope.cancel()

    async def test_capacitylimiter_acquire_nowait(self):
        limiter = create_capacity_limiter(1)
        with pytest.deprecated_call():
            await limiter.acquire_nowait()

    async def test_capacitylimiter_acquire_on_behalf_of_nowait(self):
        limiter = create_capacity_limiter(1)
        with pytest.deprecated_call():
            await limiter.acquire_on_behalf_of_nowait(object())

    async def test_capacitylimiter_set_total_tokens(self):
        limiter = create_capacity_limiter(1)
        with pytest.deprecated_call():
            await limiter.set_total_tokens(3)

        assert limiter.total_tokens == 3

    async def test_condition_release(self):
        condition = create_condition()
        condition.acquire_nowait()
        with pytest.deprecated_call():
            await condition.release()

    async def test_event_set(self):
        event = create_event()
        with pytest.deprecated_call():
            await event.set()

    async def test_lock_release(self):
        lock = create_lock()
        lock.acquire_nowait()
        with pytest.deprecated_call():
            await lock.release()

    async def test_semaphore_release(self):
        semaphore = create_semaphore(1)
        semaphore.acquire_nowait()
        with pytest.deprecated_call():
            await semaphore.release()

    async def test_taskgroup_spawn(self):
        async with create_task_group() as tg:
            with pytest.deprecated_call():
                await tg.spawn(sleep, 0)

    async def test_move_on_after(self):
        with pytest.deprecated_call():
            async with move_on_after(0):
                pass

    async def test_fail_after(self):
        with pytest.raises(TimeoutError), pytest.deprecated_call():
            async with fail_after(0):
                pass
