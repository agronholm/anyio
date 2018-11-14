import pytest

from anyio import finalize, sleep


@pytest.mark.anyio
async def test_finalize():
    async def iterable():
        try:
            yield 'blah'
        finally:
            await sleep(0)

    # This would fail with a RuntimeError on curio if async_generator.aclosing() was used instead
    async with finalize(iterable()) as agen:
        async for val in agen:  # noqa: F841
            pass
