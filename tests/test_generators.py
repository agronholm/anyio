from math import inf

import pytest

from anyio import move_on_after, sleep, wrapped_async_generator

pytestmark = pytest.mark.anyio


@wrapped_async_generator
async def squares_in_range(start, stop, timeout=inf, max_timeout_count=1):
    timeout_count = 0
    for i in range(start, stop):
        cancelled_caught = True
        with move_on_after(timeout) as cancel_scope:
            yield i ** 2
            await sleep(0)
            cancelled_caught = False
        if cancelled_caught:
            timeout_count += 1
            if timeout_count == max_timeout_count:
                break


async def test_wrapped_async_generator_full_iteration():
    last = None
    async with squares_in_range(0, 50) as squares:
        async for square in squares:
            last = square
    assert last == 49 ** 2


async def test_wrapped_async_generator_caller_exits():
    async with squares_in_range(0, 50) as squares:
        async for square in squares:
            if square >= 400:
                return
    assert False


async def test_wrapped_async_generator_caller_cancelled():
    with move_on_after(.1):
        async with squares_in_range(0, 50) as squares:
            async for square in squares:
                assert square == 0
                # the sleep will be cancelled by move_on_after above
                await sleep(.15)


async def test_wrapped_async_generator_aborts_yield():
    async with squares_in_range(0, 50, timeout=.1, max_timeout_count=1) as squares:
        async for square in squares:
            assert square == 0
            # timeout in the generator will be triggered and it will abort iteration
            await sleep(.15)


async def test_wrapped_async_generator_aborts_yield_and_continues():
    async with squares_in_range(0, 50, timeout=.1, max_timeout_count=99) as squares:
        _sum = 0
        async for square in squares:
            _sum += square
            if square == 5 ** 2:
                # this will cause the next iteration (6 ** 2) to time out
                await sleep(.15)
        assert _sum == sum(i ** 2 for i in range(0, 50)) - 6 ** 2
