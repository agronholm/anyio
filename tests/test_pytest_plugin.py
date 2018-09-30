import pytest
from async_generator import async_generator, yield_

from hyperio import sleep


@pytest.fixture
async def async_fixture():
    await sleep(0)
    return 'foo'


@pytest.fixture
@async_generator
async def asyncgen_fixture():
    await sleep(0)
    await yield_('foo')
    await sleep(0)


@pytest.mark.hyperio
async def test_fixture(async_fixture):
    assert async_fixture == 'foo'


@pytest.mark.hyperio
async def test_asyncgen_fixture(asyncgen_fixture):
    assert asyncgen_fixture == 'foo'
