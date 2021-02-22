import pytest

from anyio import maybe_async, maybe_async_cm

pytestmark = pytest.mark.anyio


def dummy():
    return 'foo'


async def dummy_async():
    return 'foo'


class DummyContextManager:
    def __enter__(self):
        return 'foo'

    def __exit__(self, exc_type, exc_val, exc_tb):
        pass


class DummyAsyncContextManager:
    async def __aenter__(self):
        return 'foo'

    async def __aexit__(self, exc_type, exc_val, exc_tb):
        pass


@pytest.mark.parametrize('function', [dummy, dummy_async], ids=['sync', 'async'])
async def test_maybe_async(function):
    assert await maybe_async(function()) == 'foo'


@pytest.mark.parametrize('cm', [DummyContextManager(), DummyAsyncContextManager()],
                         ids=['sync', 'async'])
async def test_maybe_async_cm(cm):
    async with maybe_async_cm(cm) as wrapped:
        assert wrapped == 'foo'
