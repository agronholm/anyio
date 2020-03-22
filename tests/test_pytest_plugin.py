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


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
async def test_explicit_backend(anyio_backend_name):
    assert anyio_backend_name == 'asyncio'
    assert sniffio.current_async_library() == 'asyncio'


@pytest.mark.parametrize('anyio_backend', ['asyncio'])
def test_explicit_backend_regular_function(anyio_backend_name):
    assert anyio_backend_name == 'asyncio'


@pytest.mark.parametrize('anyio_backend', ['trio', 'curio', 'asyncio'])
async def test_multiple_explicit_backend_params(anyio_backend_name):
    assert anyio_backend_name in ('trio', 'curio', 'asyncio')
    assert anyio_backend_name == sniffio.current_async_library()


class TestAnyIOBackendsFixture:
    @pytest.fixture(params=['asyncio', 'trio'])
    def anyio_backend(self, request):
        return request.param

    async def test_anyio_backend_fixture(self, anyio_backend):
        assert anyio_backend in ('asyncio', 'trio')
        assert anyio_backend == sniffio.current_async_library()
