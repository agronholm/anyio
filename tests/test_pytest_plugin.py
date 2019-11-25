import pytest
import sniffio
from async_generator import async_generator, yield_

from anyio import sleep


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


@pytest.mark.anyio
async def test_fixture(async_fixture):
    assert async_fixture == 'foo'


@pytest.mark.anyio
async def test_asyncgen_fixture(asyncgen_fixture):
    assert asyncgen_fixture == 'foo'


@pytest.mark.anyio(backend='asyncio')
async def test_explicit_backend(anyio_backend):
    assert anyio_backend == 'asyncio'


@pytest.mark.anyio(backend='asyncio')
def test_explicit_backend_regular_function(anyio_backend):
    assert anyio_backend == 'asyncio'


@pytest.mark.parametrize('backend', [
    pytest.param('trio', marks=[pytest.mark.anyio(backend='trio')]),
    pytest.param('curio', marks=[pytest.mark.anyio(backend='curio')]),
    pytest.param('asyncio', marks=[pytest.mark.anyio(backend='asyncio')])
])
async def test_multiple_explicit_backend_params(backend):
    assert backend == sniffio.current_async_library()


@pytest.mark.anyio(backend=['asyncio', 'trio'])
async def test_multiple_explicit_backends():
    pass
